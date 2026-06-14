import { expect, Page, Route } from "@playwright/test";

import { checkMarked, clickMarked, fillMarked, selectOptionMarked } from "../../../shared/utils/live-marker";
import {
  waitForEventualConsistencyPoll,
  waitForInputValue,
  waitForUiTransition,
} from "../../../shared/utils/waiting";
import { gotoEdcDashboardRoute } from "./edc-dashboard.page";

function nowMs(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

export class EdcMlAssetsPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await gotoEdcDashboardRoute(this.page, baseUrl, "ml-assets", "ML Assets");
  }

  async expectReady(): Promise<void> {
    await expect(this.page).toHaveURL(/\/edc-dashboard\/ml-assets(?:\/)?(?:\?.*)?$/, {
      timeout: 30_000,
    });
    await expect(this.searchInput()).toBeVisible({ timeout: 30_000 });
    await expect(this.page.getByText(/^Filters$/i).first()).toBeVisible({ timeout: 30_000 });
    await this.preferLargestPageSize();
  }

  async search(term: string): Promise<void> {
    await fillMarked(this.searchInput(), term);
    await waitForInputValue(this.searchInput(), term);
    await waitForUiTransition(this.page);
  }

  async waitForAssetVisible(assetId: string, timeoutMs = 120_000): Promise<void> {
    const startedAt = nowMs();
    while (nowMs() - startedAt < timeoutMs) {
      await this.search(assetId);
      if (await this.scanRenderedPagesForAsset(assetId)) {
        return;
      }
      const remainingMs = Math.max(timeoutMs - (nowMs() - startedAt), 1_000);
      const card = this.assetCard(assetId);
      try {
        await expect(card).toBeVisible({ timeout: Math.min(10_000, remainingMs) });
        return;
      } catch {
        // The dashboard can lag behind EDC catalog propagation; reload and poll again.
      }
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.expectReady();
      await waitForEventualConsistencyPoll(this.page);
    }

    if (await this.assetText(assetId).isVisible().catch(() => false)) {
      return;
    }
    throw new Error(`EDC ML Assets did not render asset ${assetId} within ${timeoutMs}ms`);
  }

  async requestCatalogManually(
    counterPartyAddress: string,
    counterPartyId?: string,
    catalogResponseBody?: unknown,
  ): Promise<void> {
    const managementRoutePattern = "**/management/v3/catalog/request*";
    const routeHandler = async (route: Route) => {
      if (catalogResponseBody !== undefined) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(catalogResponseBody),
        });
        return;
      }

      const originalRequest = route.request();
      const payload = JSON.parse(originalRequest.postData() || "{}");
      payload["@context"] = payload["@context"] || {
        "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
      };
      payload["@type"] = payload["@type"] || "CatalogRequest";
      payload.counterPartyAddress = counterPartyAddress;
      payload.protocol = payload.protocol || "dataspace-protocol-http";
      payload.querySpec = payload.querySpec || {
        offset: 0,
        limit: 100,
        filterExpression: [],
      };
      if (counterPartyId) {
        payload.counterPartyId = counterPartyId;
      }

      await route.continue({
        postData: JSON.stringify(payload),
        headers: {
          ...originalRequest.headers(),
          "content-type": "application/json",
        },
      });
    };

    await this.page.route(managementRoutePattern, routeHandler);
    const responsePromise = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        (
          response.url().includes("/management/v3/catalog/request") ||
          response.url().includes("/api/filter/catalog")
        ),
      { timeout: 45_000 },
    );

    try {
      await clickMarked(
        this.page.locator("lib-catalog-request .btn, .btn").filter({ hasText: /request manually/i }).first(),
      );
      const dialog = this.openDialog();
      await expect(dialog.getByRole("button", { name: /request catalog/i })).toBeVisible({
        timeout: 30_000,
      });
      const counterPartyIdInput = dialog.locator('input[name="counterPartyId"]').first();
      if (counterPartyId && (await counterPartyIdInput.count().catch(() => 0)) > 0) {
        await fillMarked(counterPartyIdInput, counterPartyId);
      }
      await fillMarked(dialog.locator('input[name="counterPartyAddress"]'), counterPartyAddress);
      await clickMarked(dialog.getByRole("button", { name: /request catalog/i }));

      const response = await responsePromise;
      expect(
        response.ok(),
        `ML Assets catalog request returned HTTP ${response.status()} for counterPartyAddress ${counterPartyAddress}`,
      ).toBeTruthy();
      await waitForUiTransition(this.page);
    } finally {
      await this.page.unroute(managementRoutePattern, routeHandler);
    }
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

  private openDialog() {
    return this.page.locator("dialog[open]#dashboard-dialog").first();
  }

  private assetCard(assetId: string) {
    return this.page.locator("article").filter({ hasText: assetId }).first();
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
    const preferredSize = (process.env.UI_EDC_ML_ASSETS_PAGE_SIZE || "100").trim();
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
}

export class EdcModelExecutionPage {
  private managementPaginationRouteInstalled = false;
  private externalCatalogMergeRouteInstalled = false;

  constructor(private readonly page: Page) {}

  async goto(
    baseUrl: string,
    options?: { externalCatalogCounterPartyAddress?: string; externalCatalogCounterPartyId?: string },
  ): Promise<void> {
    await this.installManagementPaginationRoute();
    await this.installExternalCatalogMergeRoute(options);
    await gotoEdcDashboardRoute(this.page, baseUrl, "model-execution", "Model Execution");
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
    const startedAt = nowMs();
    while (nowMs() - startedAt < timeoutMs) {
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

  private async installManagementPaginationRoute(): Promise<void> {
    if (this.managementPaginationRouteInstalled) {
      return;
    }
    this.managementPaginationRouteInstalled = true;

    await this.page.route("**/management/v3/*/request*", async (route) => {
      const request = route.request();
      const url = request.url();
      const isPaginatedManagementQuery =
        request.method() === "POST" &&
        (url.includes("/management/v3/assets/request") || url.includes("/management/v3/contractagreements/request"));
      if (!isPaginatedManagementQuery) {
        await route.continue();
        return;
      }

      const currentBody = this.parsePostBody(request.postData());
      const limit = url.includes("/contractagreements/") ? 5000 : 1000;
      const body = {
        "@context": currentBody["@context"] || { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
        ...currentBody,
        offset: typeof currentBody["offset"] === "number" ? currentBody["offset"] : 0,
        limit: Math.max(this.asNumber(currentBody["limit"]) || 0, limit),
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

  private async installExternalCatalogMergeRoute(options?: {
    externalCatalogCounterPartyAddress?: string;
    externalCatalogCounterPartyId?: string;
  }): Promise<void> {
    if (this.externalCatalogMergeRouteInstalled || !options?.externalCatalogCounterPartyAddress) {
      return;
    }
    this.externalCatalogMergeRouteInstalled = true;
    const counterPartyAddress = options.externalCatalogCounterPartyAddress;
    const counterPartyId = options.externalCatalogCounterPartyId;

    await this.page.route("**/api/filter/catalog**", async (route) => {
      const originalResponse = await route.fetch().catch(() => null);
      const originalBody = originalResponse ? await this.readJsonBody(originalResponse) : null;
      const managementBody = await this.requestManagementCatalog(route.request().url(), {
        counterPartyAddress,
        counterPartyId,
      });

      if (managementBody === null) {
        if (originalResponse) {
          await route.fulfill({ response: originalResponse });
        } else {
          await route.continue();
        }
        return;
      }

      const mergedBody = this.mergeCatalogBodies(originalBody, managementBody);
      await route.fulfill({
        status: originalResponse?.ok() === false ? 200 : originalResponse?.status() || 200,
        contentType: "application/json",
        body: JSON.stringify(mergedBody),
      });
    });
  }

  private async requestManagementCatalog(
    filterCatalogUrl: string,
    options: { counterPartyAddress: string; counterPartyId?: string },
  ): Promise<unknown | null> {
    const managementBaseUrl = this.managementBaseUrlForFilterCatalog(filterCatalogUrl);
    if (!managementBaseUrl) {
      return null;
    }

    const body: Record<string, unknown> = {
      "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
      "@type": "CatalogRequest",
      counterPartyAddress: options.counterPartyAddress,
      protocol: "dataspace-protocol-http",
      querySpec: {
        offset: 0,
        limit: 1000,
        filterExpression: [],
      },
    };
    if (options.counterPartyId) {
      body.counterPartyId = options.counterPartyId;
    }

    const response = await this.page.request
      .post(`${managementBaseUrl}/v3/catalog/request`, {
        data: body,
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
      })
      .catch(() => null);
    if (!response?.ok()) {
      return null;
    }
    return this.readJsonBody(response);
  }

  private managementBaseUrlForFilterCatalog(filterCatalogUrl: string): string | null {
    try {
      const url = new URL(filterCatalogUrl);
      url.pathname = url.pathname.replace(/\/api\/filter\/catalog\/?$/, "/management");
      url.search = "";
      if (!url.pathname.endsWith("/management")) {
        return null;
      }
      return url.toString().replace(/\/$/, "");
    } catch {
      return null;
    }
  }

  private mergeCatalogBodies(primaryBody: unknown, secondaryBody: unknown): unknown {
    const primaryDatasets = this.catalogDatasets(primaryBody);
    const secondaryDatasets = this.catalogDatasets(secondaryBody);
    if (secondaryDatasets.length === 0) {
      return primaryBody ?? secondaryBody;
    }
    if (primaryDatasets.length === 0) {
      return secondaryBody;
    }

    const mergedDatasets = this.mergeDatasets(primaryDatasets, secondaryDatasets);
    if (this.isRecord(primaryBody)) {
      const datasetKey = this.catalogDatasetKey(primaryBody) || this.catalogDatasetKey(secondaryBody) || "dcat:dataset";
      return {
        ...primaryBody,
        [datasetKey]: mergedDatasets,
      };
    }
    return mergedDatasets;
  }

  private mergeDatasets(primaryDatasets: unknown[], secondaryDatasets: unknown[]): unknown[] {
    const byId = new Map<string, unknown>();
    const anonymousDatasets: unknown[] = [];
    for (const dataset of [...primaryDatasets, ...secondaryDatasets]) {
      const id = this.datasetId(dataset);
      if (!id) {
        anonymousDatasets.push(dataset);
        continue;
      }
      byId.set(id, dataset);
    }
    return [...byId.values(), ...anonymousDatasets];
  }

  private catalogDatasets(body: unknown): unknown[] {
    if (Array.isArray(body)) {
      return body;
    }
    if (!this.isRecord(body)) {
      return [];
    }
    const dataset = body["dcat:dataset"] ?? body["dataset"] ?? body["datasets"];
    if (Array.isArray(dataset)) {
      return dataset;
    }
    return dataset === undefined ? [] : [dataset];
  }

  private catalogDatasetKey(body: unknown): string | null {
    if (!this.isRecord(body)) {
      return null;
    }
    for (const key of ["dcat:dataset", "dataset", "datasets"]) {
      if (Object.prototype.hasOwnProperty.call(body, key)) {
        return key;
      }
    }
    return null;
  }

  private datasetId(dataset: unknown): string | null {
    if (!this.isRecord(dataset)) {
      return null;
    }
    const id = dataset["@id"] ?? dataset["id"] ?? dataset["edc:id"];
    return typeof id === "string" && id.length > 0 ? id : null;
  }

  private async readJsonBody(response: { json(): Promise<unknown> }): Promise<unknown | null> {
    try {
      return await response.json();
    } catch {
      return null;
    }
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
}

export class EdcModelBenchmarkingPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await gotoEdcDashboardRoute(this.page, baseUrl, "model-benchmarking", "Model Benchmarking");
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
    const startedAt = nowMs();
    while (nowMs() - startedAt < timeoutMs) {
      const missing = [];
      for (const assetId of assetIds) {
        try {
          await expect(this.page.getByText(assetId).first()).toBeVisible({ timeout: 5_000 });
        } catch {
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

  async configureMapping(options: {
    inputPath?: string;
    expectedPath?: string;
    predictionPath?: string;
  }): Promise<void> {
    if (options.inputPath !== undefined) {
      const inputPath = this.page.getByRole("textbox", { name: /^Input path$/i }).first();
      await fillMarked(inputPath, options.inputPath);
      await waitForInputValue(inputPath, options.inputPath);
    }
    if (options.expectedPath !== undefined) {
      const expectedPath = this.page.getByRole("textbox", { name: /^Expected path$/i }).first();
      await fillMarked(expectedPath, options.expectedPath);
      await waitForInputValue(expectedPath, options.expectedPath);
    }
    if (options.predictionPath !== undefined) {
      const predictionPath = this.page.getByRole("textbox", { name: /^Prediction path$/i }).first();
      await fillMarked(predictionPath, options.predictionPath);
      await waitForInputValue(predictionPath, options.predictionPath);
    }
    await waitForUiTransition(this.page);
  }

  async validateInput(): Promise<void> {
    await clickMarked(this.page.getByRole("button", { name: /Validate Input/i }).first());
    await expect(this.page.getByText(/Input validation passed/i).first()).toBeVisible({ timeout: 90_000 });
    await expect(this.page.getByText(/Input validation failed/i).first()).not.toBeVisible({ timeout: 5_000 });
  }
}

export class EdcOntologyHubPage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await gotoEdcDashboardRoute(this.page, baseUrl, "ontologies", "Ontologies");
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
