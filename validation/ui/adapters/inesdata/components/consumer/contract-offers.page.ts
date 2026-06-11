import { expect, Locator, Page, type Response as PlaywrightResponse } from "@playwright/test";

import { clickMarked } from "../../../../shared/utils/live-marker";
import { snackBar } from "../../../../shared/utils/selectors";

type AttachJson = (name: string, payload: unknown) => Promise<void>;

type ContractOffersExpectationOptions = {
  assetId?: string;
  attachJson?: AttachJson;
  context?: string;
  timeoutMs?: number;
};

export type ContractOffersDiagnostics = {
  assetId?: string;
  currentUrl: string;
  reachedDetailRoute: boolean;
  contractOffersTabCount: number;
  negotiateButtonCount: number;
  visibleTabs: string[];
  visibleButtons: string[];
  bodyTextSample: string;
};

export type NegotiationSubmission = {
  url: string;
  status: number;
  negotiationId?: string;
  bodySnippet?: string;
};

export type NegotiationNotificationResult = {
  message?: string;
  warning?: string;
};

export class ContractOffersPage {
  constructor(private readonly page: Page) {}

  async collectDiagnostics(assetId?: string): Promise<ContractOffersDiagnostics> {
    return {
      assetId,
      currentUrl: this.page.url(),
      reachedDetailRoute: this.page.url().includes("/catalog/datasets/view"),
      contractOffersTabCount: await this.page
        .getByRole("tab", { name: /contract offers/i })
        .count()
        .catch(() => 0),
      negotiateButtonCount: await this.page
        .getByRole("button", { name: /negotiate contract/i })
        .count()
        .catch(() => 0),
      visibleTabs: await this.visibleTexts("[role='tab'], .mat-mdc-tab, .mat-tab-label"),
      visibleButtons: await this.visibleTexts("button"),
      bodyTextSample: await this.textSample(this.page.locator("body")),
    };
  }

  async expectReady(options: ContractOffersExpectationOptions = {}): Promise<void> {
    try {
      await expect(
        this.page.getByRole("tab", { name: /contract offers/i }),
        "Contract Offers tab is not visible in the catalog detail view",
      ).toBeVisible({
        timeout: options.timeoutMs ?? 30_000,
      });
    } catch (error: unknown) {
      const diagnostics = await this.collectDiagnostics(options.assetId);
      if (options.attachJson) {
        await options.attachJson(
          `${options.context ?? "contract-offers"}-diagnostics`,
          diagnostics,
        );
      }

      throw new Error(
        [
          "Contract Offers tab is not visible in the catalog detail view.",
          `Current URL: ${diagnostics.currentUrl}`,
          `Reached /catalog/datasets/view: ${diagnostics.reachedDetailRoute}`,
          `Contract Offers tab count: ${diagnostics.contractOffersTabCount}`,
          `Negotiate button count: ${diagnostics.negotiateButtonCount}`,
          `Visible tabs: ${JSON.stringify(diagnostics.visibleTabs)}`,
          `Visible buttons: ${JSON.stringify(diagnostics.visibleButtons)}`,
          `Original error: ${errorMessage(error)}`,
        ].join("\n"),
      );
    }
  }

  async openContractOffersTab(): Promise<void> {
    await clickMarked(this.page.getByRole("tab", { name: /contract offers/i }));
    await expect(this.page.getByRole("button", { name: /negotiate contract/i }).first()).toBeVisible({
      timeout: 15_000,
    });
  }

  async negotiateFirstOffer(): Promise<void> {
    await clickMarked(this.page.getByRole("button", { name: /negotiate contract/i }).first());
  }

  async negotiateFirstOfferAndWaitForSubmission(timeoutMs = 15_000): Promise<NegotiationSubmission | undefined> {
    const responsePromise = this.page
      .waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().includes("/management/v3/contractnegotiations"),
        { timeout: timeoutMs },
      )
      .catch(() => undefined);

    await this.negotiateFirstOffer();

    const response = await responsePromise;
    return response ? negotiationSubmissionFromResponse(response) : undefined;
  }

  async waitForNegotiationComplete(timeoutMs = 40_000): Promise<string> {
    const notification = snackBar(this.page);
    await expect(notification).toContainText(/contract negotiation complete!/i, {
      timeout: timeoutMs,
    });
    return ((await notification.textContent()) ?? "").replace(/\s+/g, " ").trim();
  }

  async readNegotiationCompletionNotification(timeoutMs = 10_000): Promise<NegotiationNotificationResult> {
    try {
      return {
        message: await this.waitForNegotiationComplete(timeoutMs),
      };
    } catch (error) {
      return {
        warning: errorMessage(error),
      };
    }
  }

  private async visibleTexts(selector: string, limit = 25): Promise<string[]> {
    const locator = this.page.locator(selector);
    const count = Math.min(await locator.count().catch(() => 0), limit);
    const texts: string[] = [];

    for (let index = 0; index < count; index += 1) {
      const item = locator.nth(index);
      if (!(await item.isVisible().catch(() => false))) {
        continue;
      }

      const text = normalizeText(await item.innerText({ timeout: 1_000 }).catch(() => ""));
      if (text) {
        texts.push(text.slice(0, 240));
      }
    }

    return texts;
  }

  private async textSample(locator: Locator): Promise<string> {
    const text = await locator.innerText({ timeout: 2_000 }).catch((error: unknown) => {
      return `<text unavailable: ${errorMessage(error)}>`;
    });
    return normalizeText(text).slice(0, 1_500);
  }
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function negotiationSubmissionFromResponse(response: PlaywrightResponse): Promise<NegotiationSubmission> {
  const text = await response.text().catch(() => "");
  let negotiationId: string | undefined;

  if (text) {
    try {
      const body = JSON.parse(text);
      negotiationId = String(body?.["@id"] || body?.id || "").trim() || undefined;
    } catch {
      negotiationId = undefined;
    }
  }

  return {
    url: response.url(),
    status: response.status(),
    negotiationId,
    bodySnippet: text ? normalizeText(text).slice(0, 500) : undefined,
  };
}
