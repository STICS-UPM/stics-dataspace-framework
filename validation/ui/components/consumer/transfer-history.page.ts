import { expect, Page } from "@playwright/test";

import { clickMarked } from "../../shared/utils/live-marker";
import { waitForEventualConsistencyPoll, waitForUiTransition } from "../../shared/utils/waiting";

// INESData can keep a successfully initiated push transfer in STARTED; storage
// evidence is validated separately by API/Newman and MinIO checks.
const ACCEPTED_TRANSFER_STATES = new Set(["STARTED", "COMPLETED", "ENDED", "TERMINATED", "DEPROVISIONED"]);

export class TransferHistoryPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/transfer-history`, {
      waitUntil: "domcontentloaded",
    });
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

  private async refresh(): Promise<void> {
    await clickMarked(this.page.getByRole("button", { name: /refresh/i }));
    await waitForUiTransition(this.page);
  }

  private async readStateOnCurrentPage(assetId: string): Promise<string | undefined> {
    const row = this.page.locator("tr.mat-mdc-row, tr.mat-row").filter({ hasText: assetId }).first();
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
      await clickMarked(previousButton);
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

    await clickMarked(nextButton);
    await waitForUiTransition(this.page);
    return true;
  }
}
