import { expect, Page } from "@playwright/test";

import { clickMarked, fillMarked, selectOptionMarked } from "../../../shared/utils/live-marker";
import {
  waitForEventualConsistencyPoll,
  waitForInputValue,
  waitForUiTransition,
} from "../../../shared/utils/waiting";
import { gotoEdcDashboardRoute } from "./edc-dashboard.page";

export class EdcAssetsPage {
  private managementPaginationRouteInstalled = false;

  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.installManagementPaginationRoute();
    await gotoEdcDashboardRoute(this.page, baseUrl, "assets", "Assets");
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/assets(?:\/)?(?:\?.*)?$/, {
      timeout: 30_000,
    });
    await expect(this.createButton()).toBeVisible({
      timeout: 30_000,
    });
    await this.preferLargestPageSize();
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
      if (await this.scanRenderedPagesForAsset(assetId)) {
        return;
      }
      const remainingMs = Math.max(timeoutMs - (Date.now() - startedAt), 1_000);
      try {
        await expect(this.assetCard(assetId)).toBeVisible({ timeout: Math.min(10_000, remainingMs) });
        return;
      } catch {
        // The dashboard asset list is eventually consistent and paginated; reload and poll again.
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
    await waitForUiTransition(this.page);
  }

  private assetCard(assetId: string) {
    return this.page.locator("lib-asset-card, article").filter({ hasText: assetId }).first();
  }

  private assetText(assetId: string) {
    return this.page.getByText(assetId).first();
  }

  private itemsPerPageSelect() {
    return this.page.getByRole("combobox", { name: /^Items$/i }).first();
  }

  private nextPageButton() {
    return this.page.getByRole("button", { name: /^»$/ }).first();
  }

  private currentPageLabel() {
    return this.page.getByRole("button", { name: /^Page \d+ of \d+$/ }).first();
  }

  private async preferLargestPageSize(): Promise<void> {
    const preferredSize = (process.env.UI_EDC_ASSETS_PAGE_SIZE || "100").trim();
    if (!preferredSize) {
      return;
    }

    const select = this.itemsPerPageSelect();
    if (!(await select.isVisible().catch(() => false))) {
      return;
    }

    const currentValue = await select.inputValue().catch(() => "");
    if (currentValue === preferredSize) {
      return;
    }

    await selectOptionMarked(select, { value: preferredSize }).catch(async () => {
      await selectOptionMarked(select, { label: preferredSize }).catch(() => undefined);
    });
    await waitForUiTransition(this.page);
  }

  private async scanRenderedPagesForAsset(assetId: string): Promise<boolean> {
    const visitedPages = new Set<string>();

    while (true) {
      if (
        (await this.assetCard(assetId).isVisible().catch(() => false)) ||
        (await this.assetText(assetId).isVisible().catch(() => false))
      ) {
        return true;
      }

      const pageLabel = (await this.currentPageLabel().textContent().catch(() => ""))?.trim() || "single-page";
      if (visitedPages.has(pageLabel)) {
        return false;
      }
      visitedPages.add(pageLabel);

      const next = this.nextPageButton();
      if (!(await next.isVisible().catch(() => false)) || await next.isDisabled().catch(() => true)) {
        return false;
      }

      await clickMarked(next);
      await waitForUiTransition(this.page);
    }
  }

  private async installManagementPaginationRoute(): Promise<void> {
    if (this.managementPaginationRouteInstalled) {
      return;
    }
    this.managementPaginationRouteInstalled = true;

    await this.page.route("**/management/v3/assets/request*", async (route) => {
      const request = route.request();
      if (request.method() !== "POST") {
        await route.continue();
        return;
      }

      const currentBody = this.parsePostBody(request.postData());
      const body = {
        "@context": currentBody["@context"] || { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
        ...currentBody,
        offset: typeof currentBody["offset"] === "number" ? currentBody["offset"] : 0,
        limit: Math.max(this.asNumber(currentBody["limit"]) || 0, 1000),
        filterExpression: Array.isArray(currentBody["filterExpression"]) ? currentBody["filterExpression"] : [],
      };

      await route.continue({
        postData: JSON.stringify(body),
        headers: {
          ...request.headers(),
          "content-type": "application/json",
          accept: request.headers()["accept"] || "application/json",
        },
      });
    });
  }

  private parsePostBody(postData: string | null): Record<string, unknown> {
    if (!postData) {
      return {};
    }
    try {
      const parsed = JSON.parse(postData);
      return this.isRecord(parsed) ? parsed : {};
    } catch {
      return {};
    }
  }

  private asNumber(value: unknown): number | null {
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === "string" && value.trim().length > 0) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  private createButton() {
    return this.page.locator("button").filter({ hasText: /\bCreate\b/i }).first();
  }

  private openDialog() {
    return this.page.locator("dialog[open]#dashboard-dialog").first();
  }
}
