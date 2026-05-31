const { expect } = require("../fixtures");
const { clickMarked, fillMarked } = require("../support/live-marker");
const { gotoDashboardRoute } = require("./navigation");

class ContractsPage {
  constructor(page, runtime) {
    this.page = page;
    this.runtime = runtime;
    this.filterInput = page.locator("lib-filter-input input");
    this.consumerProviderSwitch = page.locator("lib-consumer-provider-switch");
    this.agreementCards = page.locator("lib-contract-agreement-card");
    this.detailsDialog = page.locator("dialog#dashboard-dialog");
    this.jsonLdViewer = this.detailsDialog.locator("lib-jsonld-viewer");
  }

  async goto() {
    await gotoDashboardRoute(this.page, this.runtime, this.runtime.contractsPath, "Contracts");
  }

  async waitUntilReady() {
    await expect(this.filterInput).toBeVisible();
    await expect(this.consumerProviderSwitch).toBeVisible();
  }

  async search(text) {
    await fillMarked(this.filterInput, text);
  }

  cardByAssetId(assetId) {
    return this.agreementCards.filter({ hasText: assetId }).first();
  }

  transferButtonForCard(card) {
    return card.locator("button").filter({ hasText: /Transfer/i }).first();
  }

  detailsButtonForCard(card) {
    return card
      .locator("button")
      .filter({ has: this.page.locator("i.material-symbols-rounded", { hasText: "info" }) })
      .first();
  }

  async openDetailsForCard(card) {
    await clickMarked(this.detailsButtonForCard(card));
    await expect(this.jsonLdViewer).toBeVisible();
  }
}

module.exports = {
  ContractsPage,
};
