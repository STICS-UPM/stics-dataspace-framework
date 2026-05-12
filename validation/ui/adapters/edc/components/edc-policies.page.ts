import { expect, Page } from "@playwright/test";

import { clickMarked, fillMarked, selectOptionMarked } from "../../../shared/utils/live-marker";
import {
  waitForEventualConsistencyPoll,
  waitForInputValue,
  waitForUiTransition,
} from "../../../shared/utils/waiting";

export class EdcPoliciesPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/policies`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/policies(?:\/)?(?:\?.*)?$/, {
      timeout: 30_000,
    });
    await expect(this.createButton()).toBeVisible({
      timeout: 30_000,
    });
  }

  async createSetPolicy(policyId: string): Promise<void> {
    await clickMarked(this.createButton());

    const dialog = this.openDialog();
    await expect(dialog.locator("lib-policy-create")).toBeVisible({ timeout: 30_000 });

    await fillMarked(dialog.locator('input[name="id"]').first(), policyId);
    await selectOptionMarked(dialog.locator('select[name="policyType"]').first(), { label: "Set" });
    await waitForUiTransition(this.page);

    const createResponse = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/management/v3/policydefinitions"),
      { timeout: 45_000 },
    );

    await clickMarked(dialog.getByRole("button", { name: /create policy/i }));
    const response = await createResponse;
    expect(response.ok(), `EDC policy creation returned HTTP ${response.status()}`).toBeTruthy();
    await expect(dialog).not.toBeVisible({ timeout: 30_000 });
  }

  async waitForPolicyListed(policyId: string, timeoutMs = 60_000): Promise<void> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      await this.filterById(policyId);
      if ((await this.policyCard(policyId).count().catch(() => 0)) > 0) {
        await expect(this.policyCard(policyId)).toBeVisible({ timeout: 15_000 });
        return;
      }
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.expectReady();
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(`EDC policy ${policyId} did not appear in the provider policy list`);
  }

  private async filterById(policyId: string): Promise<void> {
    const filterInput = this.page.locator('input[placeholder*="Filter for ID"]').first();
    if ((await filterInput.count().catch(() => 0)) === 0) {
      return;
    }
    await fillMarked(filterInput, policyId);
    await waitForInputValue(filterInput, policyId);
  }

  private policyCard(policyId: string) {
    return this.page.locator("lib-policy-card").filter({ hasText: policyId }).first();
  }

  private createButton() {
    return this.page.locator("button").filter({ hasText: /\bCreate\b/i }).first();
  }

  private openDialog() {
    return this.page.locator("dialog[open]#dashboard-dialog").first();
  }
}
