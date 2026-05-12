import { expect, Page } from "@playwright/test";

import { clickMarked, fillMarked, selectOptionMarked } from "../../../shared/utils/live-marker";
import {
  waitForEventualConsistencyPoll,
  waitForInputValue,
  waitForUiTransition,
} from "../../../shared/utils/waiting";

export class EdcAssetsPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/assets`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/assets(?:\/)?(?:\?.*)?$/, {
      timeout: 30_000,
    });
    await expect(this.createButton()).toBeVisible({
      timeout: 30_000,
    });
  }

  async createHttpAsset(assetId: string, sourceUrl: string): Promise<void> {
    await clickMarked(this.createButton());

    const dialog = this.openDialog();
    await expect(dialog.locator("lib-asset-create")).toBeVisible({ timeout: 30_000 });

    await fillMarked(dialog.locator('input[name="id"]').first(), assetId);
    await fillMarked(dialog.locator('input[placeholder="Name"]').first(), `EDC UI asset ${assetId}`);
    await fillMarked(dialog.locator('input[name="contenttype"]').first(), "application/json");

    const dataTypeSelect = dialog.locator('select[name="dataType"]').first();
    await expect(dataTypeSelect).toBeVisible({ timeout: 30_000 });
    await selectOptionMarked(dataTypeSelect, { label: "HttpData" });
    await waitForUiTransition(this.page);

    const methodSelect = dialog.locator('select[name="method"]').first();
    if ((await methodSelect.count().catch(() => 0)) > 0) {
      await selectOptionMarked(methodSelect, { label: "GET" });
    }

    const baseUrlInput = dialog.locator('input[name="baseUrl"]').first();
    await expect(baseUrlInput).toBeVisible({ timeout: 30_000 });
    await fillMarked(baseUrlInput, sourceUrl);
    await waitForInputValue(baseUrlInput, sourceUrl);

    const createResponse = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/management/v3/assets"),
      { timeout: 45_000 },
    );

    await clickMarked(dialog.getByRole("button", { name: /create asset/i }));
    const response = await createResponse;
    expect(response.ok(), `EDC asset creation returned HTTP ${response.status()}`).toBeTruthy();
    await expect(dialog).not.toBeVisible({ timeout: 30_000 });
  }

  async waitForAssetListed(assetId: string, timeoutMs = 60_000): Promise<void> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      await this.filterById(assetId);
      if ((await this.assetCard(assetId).count().catch(() => 0)) > 0) {
        await expect(this.assetCard(assetId)).toBeVisible({ timeout: 15_000 });
        return;
      }
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.expectReady();
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(`EDC asset ${assetId} did not appear in the provider asset list`);
  }

  private async filterById(assetId: string): Promise<void> {
    const filterInput = this.page.locator('input[placeholder*="Filter for ID"]').first();
    if ((await filterInput.count().catch(() => 0)) === 0) {
      return;
    }
    await fillMarked(filterInput, assetId);
    await waitForInputValue(filterInput, assetId);
  }

  private assetCard(assetId: string) {
    return this.page.locator("lib-asset-card").filter({ hasText: assetId }).first();
  }

  private createButton() {
    return this.page.locator("button").filter({ hasText: /\bCreate\b/i }).first();
  }

  private openDialog() {
    return this.page.locator("dialog[open]#dashboard-dialog").first();
  }
}
