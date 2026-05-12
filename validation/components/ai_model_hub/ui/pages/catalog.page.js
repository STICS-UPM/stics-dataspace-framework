const { expect } = require("../fixtures");
const { checkMarked, clickMarked, fillMarked } = require("../support/live-marker");

class CatalogPage {
  constructor(page, runtime) {
    this.page = page;
    this.runtime = runtime;
    this.root = page.locator("lib-catalog-request");
    this.requestButton = page.locator("lib-catalog-request .btn");
    this.catalogCards = page.locator("lib-catalog-card");
    this.errorAlert = page.locator(".alert-error");
    this.emptyStateMessage = page.locator("section").getByText(/No catalog has been requested yet/i);
    this.requestDialog = page.locator("dialog#dashboard-dialog");
    this.counterPartyAddressInput = this.requestDialog.locator("input[name='counterPartyAddress']");
    this.counterPartyIdInput = this.requestDialog.locator("input[name='counterPartyId']");
    this.requestCatalogButton = this.requestDialog.locator("button[type='submit']");
    this.negotiationDialog = page.locator("dialog#dashboard-dialog");
    this.offerRadioButtons = this.negotiationDialog.locator("input[type='radio']");
    this.negotiateButton = this.negotiationDialog.locator("button").filter({ hasText: /Negotiate/i }).first();
    this.goToContractsButton = this.negotiationDialog.locator("button, div[role='button']").filter({
      hasText: /Go to Contracts/i,
    });
    this.progressTitle = this.negotiationDialog.getByRole("heading", { name: /Contract Negotiation/i });
    this.paginationLabel = page.getByRole("button", { name: /Page \d+ of \d+/ }).first();
    this.nextPageButton = page.getByRole("button", { name: "»" }).first();
  }

  async goto() {
    await this.page.goto(`${this.runtime.baseUrl}${this.runtime.catalogPath}`);
  }

  async waitUntilReady() {
    await expect(this.root).toBeVisible();
  }

  async requestCatalogManually(counterPartyAddress, counterPartyId = "") {
    await clickMarked(this.requestButton);
    await expect(this.requestDialog).toBeVisible();
    if (counterPartyId) {
      await fillMarked(this.counterPartyIdInput, counterPartyId);
    }
    await fillMarked(this.counterPartyAddressInput, counterPartyAddress);
    await expect(this.requestCatalogButton).toBeEnabled();
    await clickMarked(this.requestCatalogButton);
    await expect(this.requestDialog).toBeHidden({ timeout: 20000 });
  }

  catalogCardByText(text) {
    return this.catalogCards.filter({ hasText: text }).first();
  }

  async findCatalogCardAcrossPages(text, maxPages = 10) {
    const visitedPages = new Set();

    for (let attempt = 0; attempt < maxPages; attempt += 1) {
      const card = this.catalogCardByText(text);
      if ((await card.count()) > 0) {
        return card;
      }

      const currentPageLabel = ((await this.paginationLabel.textContent().catch(() => "")) || "").trim();
      if (!currentPageLabel || visitedPages.has(currentPageLabel)) {
        break;
      }
      visitedPages.add(currentPageLabel);

      const nextDisabled = await this.nextPageButton.isDisabled().catch(() => false);
      if (nextDisabled) {
        break;
      }

      await clickMarked(this.nextPageButton);
      await this.page.waitForLoadState("domcontentloaded", { timeout: 1000 }).catch(() => {});
    }

    throw new Error(`Catalog card '${text}' was not visible in the paginated catalog results`);
  }

  negotiateButtonForCard(card) {
    return card.locator("button").filter({ hasText: /Negotiate/i }).first();
  }

  async openNegotiationForCard(card) {
    await clickMarked(this.negotiateButtonForCard(card));
    await expect(this.negotiationDialog).toBeVisible();
  }

  async selectFirstOffer() {
    await expect(this.offerRadioButtons.first()).toBeVisible();
    await checkMarked(this.offerRadioButtons.first());
  }

  async startNegotiation() {
    await expect(this.negotiateButton).toBeVisible();
    await expect(this.negotiateButton).toBeEnabled();
    await clickMarked(this.negotiateButton);
  }
}

module.exports = {
  CatalogPage,
};
