const { clickMarked, fillMarked } = require("../support/live-marker");
const { resolveOntologyHubTimeouts } = require("../runtime");

const {
  readyTimeoutMs,
  navigationTimeoutMs,
} = resolveOntologyHubTimeouts();

class OntologyHubVocabCatalogPage {
  constructor(page) {
    this.page = page;
    this.searchInput = page.locator("#searchInput");
  }

  async goto(baseUrl, query) {
    const url = new URL("/dataset/vocabs", baseUrl);
    if (query) {
      url.searchParams.set("q", query);
    }
    await this.page.goto(url.toString(), { waitUntil: "commit", timeout: navigationTimeoutMs });
    await this.page.waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs }).catch(() => {});
  }

  async expectReady() {
    await this.searchInput.waitFor({ state: "visible" });
  }

  resultItems() {
    return this.page.locator("#SearchGrid li.SearchBoxvocabulary, #SearchGrid li");
  }

  async waitForResults() {
    await this.page.locator(".count-items .count").first().waitFor({
      state: "attached",
      timeout: readyTimeoutMs,
    });
    await this.resultItems().first().waitFor({
      state: "attached",
      timeout: readyTimeoutMs,
    });
  }

  async expectResultVisible(prefixOrLabel) {
    await this.page
      .locator("#SearchGrid")
      .getByText(prefixOrLabel, { exact: false })
      .first()
      .waitFor({ state: "visible", timeout: readyTimeoutMs });
  }

  async openResult(prefix) {
    const exactPrefix = new RegExp(`^\\s*${escapeRegExp(prefix)}\\s*$`, "i");
    const target = this.page.locator("#SearchGrid .prefix a").filter({ hasText: exactPrefix }).first();
    await target.waitFor({ state: "visible", timeout: readyTimeoutMs });
    const label = ((await target.textContent()) || "").trim();
    await clickMarked(target);
    return label;
  }

  facet(groupLabel) {
    return this.page
      .locator(".facet")
      .filter({ has: this.page.locator(".facet-heading", { hasText: groupLabel }) })
      .first();
  }

  facetLink(groupLabel, valueLabel) {
    return this.facet(groupLabel).locator("a").filter({ hasText: valueLabel }).first();
  }

  firstFacetLink(groupLabel) {
    return this.facet(groupLabel).locator("a").first();
  }

  async facetLabels(groupLabel) {
    return this.facet(groupLabel)
      .locator("a")
      .evaluateAll((nodes) =>
        nodes
          .map((node) => (node.textContent || "").trim())
          .filter(Boolean),
      );
  }

  async facetHref(locator) {
    const href = await locator.getAttribute("href");
    return String(href || "").trim();
  }

  async currentResultCount() {
    const countLocator = this.page.locator(".count-items .count").first();
    const countText =
      (await countLocator.count().catch(() => 0)) > 0
        ? await countLocator.textContent().catch(() => "")
        : "";
    const parsed = Number(countText || "0");
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
    return this.resultItems().count();
  }

  suggestionItems() {
    return this.page.locator("ul.ui-autocomplete li");
  }

  async search(query) {
    await fillMarked(this.searchInput, "");
    await fillMarked(this.searchInput, query);
  }

  async waitForSuggestions() {
    await this.suggestionItems().first().waitFor({ state: "visible" });
  }

  async suggestionLabels() {
    return this.suggestionItems().evaluateAll((nodes) =>
      nodes
        .map((node) => (node.textContent || "").trim())
        .filter(Boolean),
    );
  }

  async openSuggestion(prefix) {
    const target = prefix
      ? this.suggestionItems()
          .filter({ hasText: new RegExp(`^\\s*${escapeRegExp(prefix)}\\s*$`, "i") })
          .first()
      : this.suggestionItems().first();
    await target.waitFor({ state: "visible" });
    const label = ((await target.textContent()) || "").trim();
    await clickMarked(target);
    return label;
  }
}

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

module.exports = {
  OntologyHubVocabCatalogPage,
};
