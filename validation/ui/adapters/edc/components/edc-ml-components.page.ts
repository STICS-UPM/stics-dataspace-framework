import { expect, Page } from "@playwright/test";

import { checkMarked, clickMarked, fillMarked, selectOptionMarked } from "../../../shared/utils/live-marker";
import {
  waitForEventualConsistencyPoll,
  waitForInputValue,
  waitForUiTransition,
} from "../../../shared/utils/waiting";

function dashboardUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/$/, "")}/${path.replace(/^\/+/, "")}`;
}

export class EdcMlAssetsPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(dashboardUrl(baseUrl, "ml-assets"), {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/ml-assets(?:\/)?(?:\?.*)?$/, {
      timeout: 30_000,
    });
    await expect(this.searchInput()).toBeVisible({ timeout: 30_000 });
    await expect(this.page.getByText(/^Filters$/i).first()).toBeVisible({ timeout: 30_000 });
  }

  async search(term: string): Promise<void> {
    await fillMarked(this.searchInput(), term);
    await waitForInputValue(this.searchInput(), term);
    await waitForUiTransition(this.page);
  }

  async waitForAssetVisible(assetId: string, timeoutMs = 120_000): Promise<void> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      await this.search(assetId);
      if (await this.assetCard(assetId).isVisible().catch(() => false)) {
        await expect(this.assetCard(assetId)).toBeVisible({ timeout: 15_000 });
        return;
      }
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.expectReady();
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(`EDC ML Assets did not render asset ${assetId} within ${timeoutMs}ms`);
  }

  async expectAssetHidden(assetId: string): Promise<void> {
    await expect(this.assetCard(assetId)).not.toBeVisible({ timeout: 5_000 });
  }

  async openDetails(assetId: string): Promise<void> {
    const card = this.assetCard(assetId);
    await expect(card).toBeVisible({ timeout: 30_000 });
    const detailsButton = card
      .locator("button")
      .filter({ has: this.page.locator(".material-symbols-rounded", { hasText: /^info$/i }) })
      .first();
    await expect(detailsButton, `Details button for ${assetId} is not visible`).toBeVisible({ timeout: 15_000 });
    await clickMarked(detailsButton);
    await expect(this.page.locator("dialog[open]#dashboard-dialog, .modal, .card").filter({ hasText: assetId }).first())
      .toBeVisible({ timeout: 30_000 });
  }

  private searchInput() {
    return this.page.locator("input[placeholder*='Search model assets']").first();
  }

  private assetCard(assetId: string) {
    return this.page.locator("article.card").filter({ hasText: assetId }).first();
  }
}

export class EdcModelExecutionPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(dashboardUrl(baseUrl, "model-execution"), {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/model-execution(?:\/)?(?:\?.*)?$/, {
      timeout: 30_000,
    });
    await expect(this.page.getByRole("heading", { name: /^Model Execution$/i }).first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(this.assetSelect()).toBeVisible({ timeout: 30_000 });
    await expect(this.page.getByText(/^Input JSON$/i).first()).toBeVisible({ timeout: 30_000 });
  }

  async waitForExecutableAsset(assetId: string, timeoutMs = 120_000): Promise<void> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      const options = await this.assetSelect().locator("option").allTextContents();
      if (options.some((option) => option.includes(assetId))) {
        return;
      }
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.expectReady();
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(`Executable asset ${assetId} did not appear in EDC Model Execution`);
  }

  async executeAsset(assetId: string, payload: Record<string, unknown>, timeoutMs = 90_000): Promise<void> {
    await selectOptionMarked(this.assetSelect(), { value: assetId });
    await waitForUiTransition(this.page);
    await fillMarked(this.page.locator("textarea").first(), JSON.stringify(payload, null, 2));

    const responsePromise = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().includes("/edc-dashboard-api/") &&
        response.url().includes("/infer"),
      { timeout: timeoutMs },
    );
    await clickMarked(this.page.getByRole("button", { name: /^Execute$/i }).first());
    const response = await responsePromise;
    expect(response.ok(), `EDC model execution returned HTTP ${response.status()}`).toBeTruthy();
    await expect(this.page.getByText(/^Output$/i).first()).toBeVisible({ timeout: timeoutMs });
  }

  private assetSelect() {
    return this.page.locator("select").first();
  }
}

export class EdcModelBenchmarkingPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(dashboardUrl(baseUrl, "model-benchmarking"), {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/model-benchmarking(?:\/)?(?:\?.*)?$/, {
      timeout: 30_000,
    });
    await expect(this.page.getByRole("heading", { name: /^Model Benchmarking$/i }).first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(this.page.getByRole("button", { name: /Refresh Assets/i }).first()).toBeVisible({
      timeout: 30_000,
    });
  }

  async waitForExecutableAssets(assetIds: string[], timeoutMs = 120_000): Promise<void> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      const missing = [];
      for (const assetId of assetIds) {
        if (!(await this.page.getByText(assetId).first().isVisible().catch(() => false))) {
          missing.push(assetId);
        }
      }
      if (missing.length === 0) {
        return;
      }
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.expectReady();
      await waitForEventualConsistencyPoll(this.page);
    }

    throw new Error(`EDC Model Benchmarking did not render assets ${assetIds.join(", ")}`);
  }

  async selectAssets(assetIds: string[]): Promise<void> {
    for (const assetId of assetIds) {
      const row = this.page.locator("label").filter({ hasText: assetId }).first();
      await expect(row, `Benchmark asset row for ${assetId} is not visible`).toBeVisible({ timeout: 30_000 });
      const checkbox = row.locator('input[type="checkbox"]').first();
      if (!(await checkbox.isChecked().catch(() => false))) {
        await checkMarked(checkbox);
      }
    }
  }

  async uploadDataset(filePath: string): Promise<void> {
    await this.page.locator('input[type="file"]').first().setInputFiles(filePath);
    await expect(this.page.getByText(/Loaded \d+ rows from/i).first()).toBeVisible({ timeout: 30_000 });
  }

  async validateInput(): Promise<void> {
    await clickMarked(this.page.getByRole("button", { name: /Validate Input/i }).first());
    await expect(
      this.page.getByText(/Input validation passed|Validation|Input validation failed/i).first(),
    ).toBeVisible({ timeout: 90_000 });
  }
}

export class EdcOntologyHubPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(dashboardUrl(baseUrl, "ontologies"), {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/ontologies(?:\/)?(?:\?.*)?$/, {
      timeout: 30_000,
    });
    await expect(this.page.getByText(/Ontology Hub endpoint/i).first()).toBeVisible({ timeout: 30_000 });
    await expect(this.page.locator("a").filter({ hasText: /Open Ontology Hub/i }).first()).toBeVisible({
      timeout: 30_000,
    });
  }
}
