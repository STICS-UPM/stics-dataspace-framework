import { expect, Locator, Page } from "@playwright/test";

import { clickMarked } from "../../shared/utils/live-marker";
import { waitForUiTransition } from "../../shared/utils/waiting";

type AttachJson = (name: string, payload: unknown) => Promise<void>;

type DetailExpectationOptions = {
  assetId?: string;
  attachJson?: AttachJson;
  context?: string;
  timeoutMs?: number;
};

export type CatalogDetailDiagnostics = {
  assetId?: string;
  currentUrl: string;
  reachedDetailRoute: boolean;
  detailMarkerCount: number;
  contractOffersTabCount: number;
  visibleHeadings: string[];
  visibleButtons: string[];
  bodyTextSample: string;
};

const DETAIL_MARKERS =
  /Go back|Volver|Asset information|Informaci[oó]n del asset|Contract Offers|Ofertas de contrato|General information|Informaci[oó]n general/i;

export class CatalogPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/catalog`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/catalog/);
  }

  async showLargestPageSize(): Promise<void> {
    const pageSizeCombobox = this.page
      .getByRole("combobox", { name: /items per page/i })
      .first();

    if ((await pageSizeCombobox.count()) === 0) {
      return;
    }

    const currentRange = await this.paginatorRangeText();
    await clickMarked(pageSizeCombobox, { force: true });
    const largestOption = this.page.getByRole("option", { name: /^\s*20\s*$/ }).first();
    const optionVisible = await largestOption
      .waitFor({ state: "visible", timeout: 3_000 })
      .then(() => true)
      .catch(() => false);
    if (!optionVisible) {
      await this.page.keyboard.press("Escape").catch(() => undefined);
      return;
    }

    await clickMarked(largestOption, { force: true });
    await this.page.waitForFunction(
      (previousRange) => {
        const range = document
          .querySelector(".mat-mdc-paginator-range-label, .mat-paginator-range-label")
          ?.textContent
          ?.replace(/\s+/g, " ")
          .trim();
        return !previousRange || (range && range !== previousRange);
      },
      currentRange,
      { timeout: 3_000 },
    ).catch(() => undefined);
    await waitForUiTransition(this.page);
  }

  async openFirstDetails(): Promise<boolean> {
    const detailButton = this.page
      .locator("button:visible")
      .filter({ hasText: /view details and contract offers/i })
      .first();

    if ((await detailButton.count()) === 0) {
      return false;
    }

    await clickMarked(detailButton);
    await waitForUiTransition(this.page);
    return true;
  }

  async openDetailsForAsset(assetId: string): Promise<boolean> {
    const clickedByDom = await this.clickAssetCardButtonByDom(assetId);
    if (clickedByDom) {
      await waitForUiTransition(this.page);
      return true;
    }

    const detailButton = this.page
      .locator("mat-card, .card, [class*='card']")
      .filter({ hasText: assetId })
      .getByRole("button", { name: /view details and contract offers/i })
      .first();

    if ((await detailButton.count()) > 0) {
      try {
        await clickMarked(detailButton, { force: true });
        await waitForUiTransition(this.page);
        return true;
      } catch {
        // Fall through to the DOM fallback below. Some Material card versions
        // expose the accessible button name inconsistently under test.
      }
    }

    const assetText = this.page.getByText(assetId, { exact: true }).first();
    if ((await assetText.count()) === 0) {
      return false;
    }

    const fallbackCard = assetText
      .locator("xpath=ancestor::*[.//button[contains(normalize-space(.), 'View details and contract offers')]][1]");
    const fallbackButtonByText = fallbackCard
      .locator("button")
      .filter({ hasText: /view details and contract offers/i })
      .first();

    if ((await fallbackButtonByText.count()) > 0) {
      try {
        await clickMarked(fallbackButtonByText, { force: true });
        await waitForUiTransition(this.page);
        return true;
      } catch {
        // Fall through to the accessible-name fallback below.
      }
    }

    const fallbackButton = fallbackCard
      .getByRole("button", { name: /view details and contract offers/i })
      .first();

    if ((await fallbackButton.count()) > 0) {
      try {
        await clickMarked(fallbackButton, { force: true });
        await waitForUiTransition(this.page);
        return true;
      } catch {
        // Fall through to the DOM fallback below.
      }
    }

    return false;
  }

  async hasNextPage(): Promise<boolean> {
    const nextButton = this.nextPageButton();

    if ((await nextButton.count()) === 0) {
      return false;
    }

    return nextButton.isEnabled().catch(() => false);
  }

  async goToNextPage(): Promise<boolean> {
    const nextButton = this.nextPageButton();

    if ((await nextButton.count()) === 0) {
      return false;
    }

    if (!(await nextButton.isEnabled().catch(() => false))) {
      return false;
    }

    const currentRange = await this.paginatorRangeText();
    await clickMarked(nextButton, { force: true });
    let changed = await this.waitForPaginatorRangeChange(currentRange);
    if (!changed && (await this.clickNextPageButtonByDom())) {
      changed = await this.waitForPaginatorRangeChange(currentRange);
    }
    await waitForUiTransition(this.page);
    return changed;
  }

  private nextPageButton(): Locator {
    return this.page
      .getByRole("button", { name: /next page/i })
      .or(this.page.locator("button.mat-paginator-navigation-next, button[aria-label*='Next page']"))
      .first();
  }

  private async paginatorRangeText(): Promise<string> {
    return this.page
      .locator(".mat-mdc-paginator-range-label, .mat-paginator-range-label")
      .first()
      .innerText({ timeout: 1_000 })
      .then(normalizeText)
      .catch(() => "");
  }

  private async waitForPaginatorRangeChange(previousRange: string): Promise<boolean> {
    return this.page.waitForFunction(
      (rangeBefore) => {
        const range = document
          .querySelector(".mat-mdc-paginator-range-label, .mat-paginator-range-label")
          ?.textContent
          ?.replace(/\s+/g, " ")
          .trim();
        return !rangeBefore || (range && range !== rangeBefore);
      },
      previousRange,
      { timeout: 3_000 },
    ).then(() => true).catch(() => false);
  }

  private async clickAssetCardButtonByDom(assetId: string): Promise<boolean> {
    return this.page.evaluate((targetAssetId) => {
      const cards = Array.from(document.querySelectorAll(".card, mat-card, [class*='card']"));
      const card = cards.find((candidate) => candidate.textContent?.includes(targetAssetId));
      const button = card?.querySelector("button");
      if (button instanceof HTMLElement) {
        button.click();
        return true;
      }

      const textMatches = Array.from(document.querySelectorAll("body *")).filter((candidate) =>
        candidate.textContent?.includes(targetAssetId),
      );
      for (const match of textMatches) {
        let current: Element | null = match;
        for (let depth = 0; current && depth < 8; depth += 1) {
          const detailButton = Array.from(current.querySelectorAll("button")).find((candidate) =>
            /view details and contract offers/i.test(candidate.textContent || ""),
          );
          if (detailButton instanceof HTMLElement) {
            detailButton.click();
            return true;
          }
          current = current.parentElement;
        }
      }
      return false;
    }, assetId);
  }

  private async clickNextPageButtonByDom(): Promise<boolean> {
    return this.page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const button = buttons.find((candidate) => {
        const label = `${candidate.getAttribute("aria-label") || ""} ${candidate.className || ""}`;
        return /next page|mat-.*paginator.*next/i.test(label);
      });
      if (!(button instanceof HTMLButtonElement) || button.disabled || button.getAttribute("aria-disabled") === "true") {
        return false;
      }
      button.click();
      return true;
    });
  }

  async collectDetailDiagnostics(assetId?: string): Promise<CatalogDetailDiagnostics> {
    const detailMarkers = this.page.getByText(DETAIL_MARKERS);
    return {
      assetId,
      currentUrl: this.page.url(),
      reachedDetailRoute: this.page.url().includes("/catalog/datasets/view"),
      detailMarkerCount: await detailMarkers.count().catch(() => 0),
      contractOffersTabCount: await this.page
        .getByRole("tab", { name: /contract offers/i })
        .count()
        .catch(() => 0),
      visibleHeadings: await this.visibleTexts("h1, h2, h3, mat-card-title, .mat-mdc-tab, .mat-tab-label"),
      visibleButtons: await this.visibleTexts("button"),
      bodyTextSample: await this.textSample(this.page.locator("body")),
    };
  }

  async expectDetailsVisible(options: DetailExpectationOptions = {}): Promise<void> {
    const markers = this.page.getByText(DETAIL_MARKERS);

    try {
      await expect(
        markers.first(),
        "Catalog detail view did not render after opening asset details",
      ).toBeVisible({ timeout: options.timeoutMs ?? 15_000 });
    } catch (error: unknown) {
      const diagnostics = await this.collectDetailDiagnostics(options.assetId);
      if (options.attachJson) {
        await options.attachJson(
          `${options.context ?? "catalog-detail"}-diagnostics`,
          diagnostics,
        );
      }

      throw new Error(
        [
          "Catalog detail view did not render after opening asset details.",
          `Current URL: ${diagnostics.currentUrl}`,
          `Reached /catalog/datasets/view: ${diagnostics.reachedDetailRoute}`,
          `Detail marker count: ${diagnostics.detailMarkerCount}`,
          `Contract Offers tab count: ${diagnostics.contractOffersTabCount}`,
          `Visible headings: ${JSON.stringify(diagnostics.visibleHeadings)}`,
          `Visible buttons: ${JSON.stringify(diagnostics.visibleButtons)}`,
          `Original error: ${errorMessage(error)}`,
        ].join("\n"),
      );
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
