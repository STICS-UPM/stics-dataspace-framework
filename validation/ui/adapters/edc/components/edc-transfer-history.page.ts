import { expect, Page } from "@playwright/test";

import { waitForEventualConsistencyPoll } from "../../../shared/utils/waiting";

const SUCCESS_STATES = new Set(["COMPLETED", "STARTED"]);
const FAILURE_STATES = new Set(["TERMINATED", "DEPROVISIONED", "SUSPENDED", "ERROR"]);

export class EdcTransferHistoryPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/transfer-history`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/transfer-history(?:\/)?(?:\?.*)?$/);
    await expect(this.page.locator("lib-transfer-history-table").first()).toBeVisible({
      timeout: 30_000,
    });
  }

  async waitForSuccessfulTransfer(assetId: string, timeoutMs = 90_000): Promise<string> {
    const startedAt = Date.now();
    let lastState: string | undefined;

    while (Date.now() - startedAt < timeoutMs) {
      const state = await this.readStateForAsset(assetId);
      if (state) {
        lastState = state;
        if (FAILURE_STATES.has(state)) {
          throw new Error(`Transfer for asset ${assetId} reached failure state ${state}`);
        }
        if (SUCCESS_STATES.has(state)) {
          return state;
        }
      }

      await this.page.reload({ waitUntil: "domcontentloaded" });
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(
      `Transfer for asset ${assetId} did not reach a success state. Last state: ${lastState ?? "not found"}`,
    );
  }

  async readStateForAsset(assetId: string): Promise<string | undefined> {
    const row = this.page.locator("tbody tr").filter({ hasText: assetId }).first();
    if ((await row.count().catch(() => 0)) === 0) {
      return undefined;
    }
    const stateCell = row.locator("td").nth(2);
    const state = ((await stateCell.textContent()) ?? "").replace(/\s+/g, " ").trim();
    return state || undefined;
  }
}
