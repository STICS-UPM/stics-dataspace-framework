import { expect, Page, Response } from "@playwright/test";

import { clickMarked } from "../../../../shared/utils/live-marker";
import { waitForEventualConsistencyPoll, waitForUiTransition } from "../../../../shared/utils/waiting";

// INESData can keep a successfully initiated push transfer in STARTED; storage
// evidence is validated separately by API/Newman and MinIO checks.
const ACCEPTED_TRANSFER_STATES = new Set(["STARTED", "COMPLETED", "ENDED", "TERMINATED", "DEPROVISIONED"]);

export class TransferHistoryPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    const transferResponse = this.waitForTransferListResponse(15_000);
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/transfer-history`, {
      waitUntil: "domcontentloaded",
    });
    await transferResponse;
    await waitForUiTransition(this.page);
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/transfer-history(?:\/)?$/);
    await expect(this.page.getByRole("button", { name: /refresh/i })).toBeVisible({
      timeout: 30_000,
    });
  }

  async waitForSuccessfulTransfer(assetId: string, timeoutMs = 60_000): Promise<string> {
    const startedAt = Date.now();
    let lastState: string | undefined;

    await this.showLargestPageSize();

    while (Date.now() - startedAt < timeoutMs) {
      const state = await this.readStateForAsset(assetId);
      if (state) {
        lastState = state;
        if (state === "ERROR") {
          throw new Error(`Transfer for asset ${assetId} reached ERROR state`);
        }
        if (ACCEPTED_TRANSFER_STATES.has(state)) {
          return state;
        }
      }

      await this.refresh();
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(
      `Transfer for asset ${assetId} did not reach an accepted transfer state. Last state: ${lastState ?? "not found"}`,
    );
  }

  async readStateForAsset(assetId: string): Promise<string | undefined> {
    await this.goToFirstPage();

    let state = await this.readStateOnCurrentPage(assetId);
    if (state) {
      return state;
    }

    while (await this.goToNextPage()) {
      state = await this.readStateOnCurrentPage(assetId);
      if (state) {
        return state;
      }
    }

    return undefined;
  }

  async showLargestPageSize(): Promise<void> {
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

    const transferResponse = this.waitForTransferListResponse(15_000);
    await clickMarked(largestOption, { force: true });
    await transferResponse;
    await waitForUiTransition(this.page);
  }

  async waitForTransferListResponse(timeoutMs = 10_000): Promise<boolean> {
    return this.page
      .waitForResponse(
        (response) => this.isSuccessfulTransferListResponse(response),
        { timeout: timeoutMs },
      )
      .then(() => true)
      .catch(() => false);
  }

  private async refresh(): Promise<void> {
    const transferResponse = this.waitForTransferListResponse(15_000);
    await clickMarked(this.page.getByRole("button", { name: /refresh/i }));
    await transferResponse;
    await waitForUiTransition(this.page);
  }

  private async readStateOnCurrentPage(assetId: string): Promise<string | undefined> {
    const row = this.page.locator("tbody tr, tr.mat-mdc-row, tr.mat-row").filter({ hasText: assetId }).first();
    if ((await row.count()) === 0) {
      return undefined;
    }

    const stateCell = row.locator("td.mat-column-state, td").first();
    const state = ((await stateCell.textContent()) ?? "").trim();
    return state || undefined;
  }

  private async goToFirstPage(): Promise<void> {
    const previousButton = this.page.locator(
      "button.mat-paginator-navigation-previous, button[aria-label*='Previous page']",
    ).first();

    if ((await previousButton.count()) === 0) {
      return;
    }

    while (await previousButton.isEnabled().catch(() => false)) {
      const transferResponse = this.waitForTransferListResponse(15_000);
      await clickMarked(previousButton);
      await transferResponse;
      await waitForUiTransition(this.page);
    }
  }

  private async goToNextPage(): Promise<boolean> {
    const nextButton = this.page.locator(
      "button.mat-paginator-navigation-next, button[aria-label*='Next page']",
    ).first();

    if ((await nextButton.count()) === 0) {
      return false;
    }

    if (!(await nextButton.isEnabled().catch(() => false))) {
      return false;
    }

    const transferResponse = this.waitForTransferListResponse(15_000);
    await clickMarked(nextButton);
    await transferResponse;
    await waitForUiTransition(this.page);
    return true;
  }

  private isSuccessfulTransferListResponse(response: Response): boolean {
    const url = response.url();
    return (
      response.request().method() === "POST" &&
      response.status() >= 200 &&
      response.status() < 300 &&
      (url.includes("/management/v3/transferprocesses/request") ||
        url.includes("/management/transferprocesses/request"))
    );
  }
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}
