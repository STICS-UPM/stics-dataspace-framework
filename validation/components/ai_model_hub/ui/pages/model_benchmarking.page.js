const { expect } = require("../fixtures");
const { checkMarked, clickMarked } = require("../support/live-marker");

class ModelBenchmarkingPage {
  constructor(page, runtime) {
    this.page = page;
    this.runtime = runtime;
    this.root = page.locator("app-model-benchmarking");
    this.heading = page.getByRole("heading", { name: "Model Benchmarking" });
    this.modelSearchInput = page.getByPlaceholder("Search by name, id, tag, or task...");
    this.datasetSearchInput = page.getByPlaceholder("Search datasets by name, id, task, tags...");
    this.refreshAssetsButton = page.getByRole("button", { name: /Refresh Assets/i });
    this.refreshDatasetsButton = page.getByRole("button", { name: /Refresh Datasets/i });
    this.loadSelectedDatasetButton = page.getByRole("button", { name: /Load Selected Dataset/i });
    this.validateInputButton = page.getByRole("button", { name: /Validate Input/i });
    this.runBenchmarkButton = page.getByRole("button", { name: /Run Benchmark/i });
    this.inputPathInput = page.getByPlaceholder("ex: input");
    this.expectedPathInput = page.getByPlaceholder("ex: expected_label");
    this.predictionPathInput = page.getByPlaceholder("ex: result.label");
    this.statusMessage = page.locator("div.text-sm.opacity-80").last();
    this.datasetParseMessage = page.locator("div.text-success").filter({
      hasText: /Loaded \d+ rows from dataspace asset/i,
    });
    this.resultsSection = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "Benchmark Results" }) })
      .first();
    this.bestModelSummary = this.resultsSection.locator("div").filter({
      hasText: /Best Model:/i,
    }).first();
    this.resultsTable = this.resultsSection.locator("table").first();
    this.resultsRows = this.resultsTable.locator("tbody tr");
    this.errorAlert = page.locator(".alert-error");
  }

  async goto() {
    await this.page.goto(`${this.runtime.baseUrl}${this.runtime.modelBenchmarkingPath}`);
  }

  async waitUntilReady() {
    await expect(this.root).toBeVisible();
    await expect(this.heading).toBeVisible();
    await expect(this.modelSearchInput).toBeVisible();
    await expect(this.datasetSearchInput).toBeVisible();
  }

  modelOptionByText(text) {
    return this.page
      .locator("label")
      .filter({
        has: this.page.locator("input[type='checkbox']"),
        hasText: text,
      })
      .first();
  }

  datasetOptionByText(text) {
    return this.page
      .locator("label")
      .filter({
        has: this.page.locator("input[type='radio'][name='dataspaceDataset']"),
        hasText: text,
      })
      .first();
  }

  async selectModelByText(text) {
    await expect(async () => {
      await this.modelSearchInput.fill(text);
      const option = this.modelOptionByText(text);
      if (!(await option.isVisible().catch(() => false)) && (await this.refreshAssetsButton.isEnabled().catch(() => false))) {
        await clickMarked(this.refreshAssetsButton);
      }
      await expect(option).toBeVisible({ timeout: 10000 });
    }).toPass({
      timeout: 60000,
      intervals: [1000, 2000, 5000],
    });

    const option = this.modelOptionByText(text);
    await checkMarked(option.locator("input[type='checkbox']"));
  }

  async selectDataspaceDatasetByText(text) {
    await expect(async () => {
      await this.datasetSearchInput.fill(text);
      const option = this.datasetOptionByText(text);
      if (!(await option.isVisible().catch(() => false)) && (await this.refreshDatasetsButton.isEnabled().catch(() => false))) {
        await clickMarked(this.refreshDatasetsButton);
      }
      await expect(option).toBeVisible({ timeout: 10000 });
    }).toPass({
      timeout: 60000,
      intervals: [1000, 2000, 5000],
    });

    const option = this.datasetOptionByText(text);
    await checkMarked(option.locator("input[type='radio']"));
  }

  async loadSelectedDataset() {
    await expect(this.loadSelectedDatasetButton).toBeEnabled();
    await clickMarked(this.loadSelectedDatasetButton);
    await expect(this.datasetParseMessage).toBeVisible({ timeout: 30000 });
  }

  async runBenchmark() {
    await expect(this.runBenchmarkButton).toBeEnabled({ timeout: 20000 });
    await clickMarked(this.runBenchmarkButton);
    await expect(this.statusMessage).toContainText(/Benchmark completed/i, { timeout: 60000 });
  }

  async waitForBenchmarkResults(expectedRows = 2) {
    await expect(this.bestModelSummary).toBeVisible({ timeout: 30000 });
    await expect(this.resultsTable).toBeVisible({ timeout: 30000 });
    await expect(this.resultsRows).toHaveCount(expectedRows, { timeout: 30000 });
  }

  async resultRowsText() {
    return this.resultsRows.allInnerTexts();
  }
}

module.exports = {
  ModelBenchmarkingPage,
};
