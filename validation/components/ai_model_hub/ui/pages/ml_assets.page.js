const { expect } = require("../fixtures");
const { clickMarked } = require("../support/live-marker");

class MlAssetsPage {
  constructor(page, runtime) {
    this.page = page;
    this.runtime = runtime;
    this.root = page.locator("app-ml-assets-browser");
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
