import { expect, Locator, Page, Response } from "@playwright/test";

import { clickMarked } from "../../../../shared/utils/live-marker";
import { waitForUiTransition } from "../../../../shared/utils/waiting";

type AttachJson = (name: string, payload: unknown) => Promise<void>;

type CatalogListKind = "any" | "direct" | "federated";

type CatalogListWaitOptions = {
  catalogKind?: CatalogListKind;
  expectedAssetId?: string;
  timeoutMs?: number;
};

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

  async goto(baseUrl: string, options: CatalogListWaitOptions = {}): Promise<void> {
    const catalogKind = options.catalogKind || "any";
    const catalogResponse = this.waitForCatalogListResponse(
      options.timeoutMs ?? 15_000,
      navigationCatalogWaitOptions(options),
    );
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/catalog`, {
      waitUntil: "domcontentloaded",
    });
    const responseObserved = await catalogResponse;
    await waitForUiTransition(this.page);
    if (!responseObserved && catalogKind !== "any") {
      const expectedAsset = options.expectedAssetId ? ` containing asset ${options.expectedAssetId}` : "";
      throw new Error(`Catalog ${catalogKind} list response${expectedAsset} was not observed after opening the catalog page`);
    }
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/catalog/);
  }

  async showLargestPageSize(options: CatalogListWaitOptions = {}): Promise<void> {
    if ((options.catalogKind || "any") === "federated") {
      return;
    }

    const pageSizeCombobox = this.page
      .getByRole("combobox", { name: /items per page/i })
      .first();

    if ((await pageSizeCombobox.count()) === 0) {
      return;
    }

    const currentValue = normalizeText(await pageSizeCombobox.innerText({ timeout: 1_000 }).catch(() => ""));
    if (/^20\b/.test(currentValue)) {
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

    const catalogKind = options.catalogKind || "any";
    const catalogResponse = this.waitForCatalogListResponse(
      options.timeoutMs ?? 15_000,
      navigationCatalogWaitOptions(options),
    );
    await clickMarked(largestOption, { force: true });
    const responseObserved = await catalogResponse;
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
    if (!responseObserved && catalogKind !== "any") {
      return;
    }
  }

  async waitForCatalogListResponse(
    timeoutMs = 10_000,
    options: CatalogListWaitOptions = {},
  ): Promise<boolean> {
    return this.page
      .waitForResponse(
        async (response) => {
          if (!this.isSuccessfulCatalogListResponse(response, options.catalogKind || "any")) {
            return false;
          }
          if (!options.expectedAssetId) {
            return true;
          }
          return this.catalogResponseContainsAsset(response, options.expectedAssetId);
        },
        { timeout: timeoutMs },
      )
      .then(() => true)
      .catch(() => false);
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
    await this.waitForAssetText(assetId, 3_000);

    for (let attempt = 0; attempt < 8; attempt += 1) {
      const clickedByDom = await this.clickAssetCardButtonByDom(assetId);
      if (clickedByDom && (await this.waitForDetailView())) {
        await waitForUiTransition(this.page);
        return true;
      }

      if (await this.waitForAssetText(assetId, 500)) {
        break;
      }

      const scrolled = await this.scrollCatalogContentDown();
      if (!scrolled) {
        break;
      }
      await waitForUiTransition(this.page);
    }

    const detailButton = this.page
      .locator("mat-card, .card, [class*='card']")
      .filter({ hasText: assetId })
      .getByRole("button", { name: /view details and contract offers/i })
      .first();

    if ((await detailButton.count()) > 0) {
      try {
        await clickMarked(detailButton, { force: true });
        if (await this.waitForDetailView()) {
          await waitForUiTransition(this.page);
          return true;
        }
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
        if (await this.waitForDetailView()) {
          await waitForUiTransition(this.page);
          return true;
        }
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
        if (await this.waitForDetailView()) {
          await waitForUiTransition(this.page);
          return true;
        }
      } catch {
        // Fall through to the DOM fallback below.
      }
    }

    return false;
  }

  private async waitForAssetText(assetId: string, timeoutMs: number): Promise<boolean> {
    return this.page
      .getByText(assetId, { exact: true })
      .first()
      .waitFor({ state: "visible", timeout: timeoutMs })
      .then(() => true)
      .catch(() => false);
  }

  async hasNextPage(): Promise<boolean> {
    const nextButton = this.nextPageButton();

    if ((await nextButton.count()) === 0) {
      return false;
    }

    return nextButton.isEnabled().catch(() => false);
  }

  async goToNextPage(options: CatalogListWaitOptions = {}): Promise<boolean> {
    const nextButton = this.nextPageButton();

    if ((await nextButton.count()) === 0) {
      return false;
    }

    if (!(await nextButton.isEnabled().catch(() => false))) {
      return false;
    }

    const currentRange = await this.paginatorRangeText();
    const catalogResponse = this.waitForCatalogListResponse(
      options.timeoutMs ?? 15_000,
      navigationCatalogWaitOptions(options),
    );
    await clickMarked(nextButton, { force: true });
    let changed = await this.waitForPaginatorRangeChange(currentRange);
    if (!changed && (await this.clickNextPageButtonByDom())) {
      changed = await this.waitForPaginatorRangeChange(currentRange);
    }
    const responseObserved = await catalogResponse;
    await waitForUiTransition(this.page);
    return changed && (options.catalogKind && options.catalogKind !== "any" ? responseObserved : true);
  }

  private nextPageButton(): Locator {
    return this.page
      .getByRole("button", { name: /next page/i })
      .or(this.page.locator("button.mat-paginator-navigation-next, button[aria-label*='Next page']"))
      .first();
  }

  private isSuccessfulCatalogListResponse(response: Response, catalogKind: CatalogListKind = "any"): boolean {
    const url = response.url();
    const isFederatedCatalog = url.includes("/management/federatedcatalog/request");
    const isDirectCatalog =
      url.includes("/management/catalog/request") ||
      url.includes("/management/v3/catalog/request");

    return (
      response.request().method() === "POST" &&
      response.status() >= 200 &&
      response.status() < 300 &&
      (catalogKind === "federated"
        ? isFederatedCatalog
        : catalogKind === "direct"
          ? isDirectCatalog
          : isFederatedCatalog || isDirectCatalog)
    );
  }

  private async catalogResponseContainsAsset(response: Response, assetId: string): Promise<boolean> {
    const body = await response.text().catch(() => "");
    return body.includes(assetId);
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
      const isDetailButton = (candidate: Element): candidate is HTMLElement =>
        candidate instanceof HTMLElement &&
        /view details and contract offers/i.test(candidate.textContent || "");

      const clickButtonNearAssetLabel = (label: Element): boolean => {
        let current: Element | null = label;
        for (let depth = 0; current && depth < 10; depth += 1) {
          if (!current.textContent?.includes(targetAssetId)) {
            current = current.parentElement;
            continue;
          }

          const detailButton = Array.from(current.querySelectorAll("button")).find(isDetailButton);
          if (detailButton) {
            detailButton.click();
            return true;
          }
          current = current.parentElement;
        }
        return false;
      };

      const exactLabels = Array.from(document.querySelectorAll("body *")).filter(
        (candidate) => candidate.textContent?.trim() === targetAssetId,
      );
      for (const label of exactLabels) {
        if (clickButtonNearAssetLabel(label)) {
          return true;
        }
      }

      const textMatches = Array.from(document.querySelectorAll("body *")).filter((candidate) =>
        candidate.textContent?.includes(targetAssetId),
      );
      for (const match of textMatches) {
        if (clickButtonNearAssetLabel(match)) {
          return true;
        }
      }
      return false;
    }, assetId);
  }

  private async scrollCatalogContentDown(): Promise<boolean> {
    return this.page.evaluate(() => {
      const candidates: Element[] = [
        document.scrollingElement || document.documentElement,
        ...Array.from(document.querySelectorAll("main, section, mat-sidenav-content, .mat-drawer-content, .mat-mdc-tab-body-content, div")),
      ].filter((element, index, all): element is Element => {
        if (!element || all.indexOf(element) !== index) {
          return false;
        }
        return element.scrollHeight > element.clientHeight + 20;
      });

      let scrolled = false;
      for (const element of candidates) {
        const before = element.scrollTop;
        const step = Math.max(Math.floor(element.clientHeight * 0.8), 240);
        element.scrollTop = Math.min(element.scrollTop + step, element.scrollHeight - element.clientHeight);
        if (element.scrollTop !== before) {
          scrolled = true;
        }
      }
      return scrolled;
    });
  }

  private async waitForDetailView(timeoutMs = 5_000): Promise<boolean> {
    await waitForUiTransition(this.page);
    const markers = this.page.getByText(DETAIL_MARKERS).first();
    return markers.waitFor({ state: "visible", timeout: timeoutMs })
      .then(() => true)
      .catch(() => this.page.url().includes("/catalog/datasets/view"));
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

function navigationCatalogWaitOptions(options: CatalogListWaitOptions): CatalogListWaitOptions {
  return {
    ...options,
    expectedAssetId: undefined,
  };
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
