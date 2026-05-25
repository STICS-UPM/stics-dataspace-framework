const { expect } = require("../fixtures");
const { checkMarked, clickMarked, fillMarked, selectOptionMarked } = require("../support/live-marker");

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

class MlAssetsPage {
  constructor(page, runtime) {
    this.page = page;
    this.runtime = runtime;
    this.root = page.locator("app-ml-assets-browser");
    this.connectorSelect = this.root.locator("select").first();
    this.searchInput = page.locator("lib-filter-input input");
    this.filterHeading = page.getByRole("heading", { name: "Filters" });
    this.clearFiltersButton = page.locator("aside button").filter({ hasText: "Clear" });
    this.errorAlert = page.locator(".alert-error");
    this.assetCards = page.locator("article.card");
    this.filterCheckboxes = page.locator("aside input[type='checkbox']");
    this.noResultsMessage = page.locator("section p.text-sm.text-center.opacity-60");
    this.detailsDialog = page.locator("dialog#dashboard-dialog");
    this.detailsDialogTitle = this.detailsDialog.locator("h2.text-2xl");
    this.detailsDialogAssetId = this.detailsDialog.getByText(/Asset ID:/i);
    this.overviewTab = this.detailsDialog.getByRole("button", { name: "Overview" });
    this.contractOffersTab = this.detailsDialog.getByRole("button", { name: "Contract Offers" });
    this.rawPayloadTab = this.detailsDialog.getByRole("button", { name: "Raw Payload" });
    this.detailsDialogCloseButton = this.detailsDialog.locator("form[method='dialog'] button").first();
  }

  async goto() {
    await this.page.goto(`${this.runtime.baseUrl}${this.runtime.mlAssetsPath}`);
  }

  async waitUntilReady() {
    await expect(this.root).toBeVisible();
    await expect(this.searchInput).toBeVisible();
    await Promise.race([
      this.assetCards.first().waitFor({ state: "visible", timeout: 15000 }).catch(() => null),
      this.noResultsMessage.first().waitFor({ state: "visible", timeout: 15000 }).catch(() => null),
      this.errorAlert.first().waitFor({ state: "visible", timeout: 15000 }).catch(() => null),
    ]);
  }

  cardByText(text) {
    return this.assetCards.filter({ hasText: text }).first();
  }

  cardsByText(text) {
    return this.assetCards.filter({ hasText: text });
  }

  filterSection(sectionName) {
    return this.page.locator("aside details").filter({ hasText: sectionName }).first();
  }

  filterOption(sectionName, optionText) {
    return this.filterSection(sectionName).locator("label").filter({ hasText: optionText }).first();
  }

  filterCheckbox(sectionName, optionText) {
    return this.filterOption(sectionName, optionText).locator("input[type='checkbox']").first();
  }

  async search(text) {
    await fillMarked(this.searchInput, text);
  }

  async switchToConnector(connectorName) {
    await expect(this.connectorSelect).toBeVisible({ timeout: 15000 });
    await selectOptionMarked(this.connectorSelect, { label: connectorName });
    await expect(this.connectorSelect.locator("option:checked")).toHaveText(
      new RegExp(`^\\s*${escapeRegExp(connectorName)}\\s*$`, "i"),
    );
    await this.page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => undefined);
  }

  async applyFilter(sectionName, optionText) {
    const checkbox = this.filterCheckbox(sectionName, optionText);
    await expect(checkbox).toBeVisible({ timeout: 15000 });
    await checkMarked(checkbox);
    await expect(checkbox).toBeChecked();
  }

  async expectCardVisible(text) {
    await expect(this.cardByText(text)).toBeVisible({ timeout: 15000 });
  }

  async expectCardHidden(text) {
    await expect(this.cardsByText(text)).toHaveCount(0, { timeout: 15000 });
  }

  async openDetailsForCard(card) {
    await clickMarked(
      card
        .locator("button")
        .filter({ has: this.page.locator("i.material-symbols-rounded", { hasText: "info" }) })
        .first(),
    );
    await expect(this.detailsDialog).toBeVisible();
  }
}

module.exports = {
  MlAssetsPage,
};
