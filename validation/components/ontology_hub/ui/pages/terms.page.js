const { clickMarked } = require("../support/live-marker");
const { resolveOntologyHubTimeouts } = require("../runtime");

const {
  readyTimeoutMs,
  navigationTimeoutMs,
} = resolveOntologyHubTimeouts();

class OntologyHubTermsPage {
  constructor(page) {
    this.page = page;
  }

  async goto(baseUrl, query) {
    const url = new URL("/dataset/terms", baseUrl);
    if (query) {
      url.searchParams.set("q", query);
    }
    await this.page.goto(url.toString(), { waitUntil: "commit", timeout: navigationTimeoutMs });
    await this.page.waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs }).catch(() => {});
  }

  async expectReady() {
    await this.page.locator("#searchInput").waitFor({ state: "visible" });
    await this.expectHealthyPage();
  }

  async expectHealthyPage() {
    const headingLocator = this.page.locator("h1").first();
    const heading =
      (await headingLocator.count().catch(() => 0)) > 0
        ? ((await headingLocator.textContent().catch(() => "")) || "").trim()
        : "";
    if (/404|500|oops!/i.test(heading)) {
      throw new Error(`Ontology Hub terms page failed to load: ${heading}`);
    }
  }

  resultItems() {
    return this.page.locator(
      "#SearchGrid li.SearchBoxclass, #SearchGrid li, #SearchGrid .prefixedName a, section#posts a[href*='/dataset/terms/']",
    );
  }

  async waitForResults() {
    await this.expectHealthyPage();
    await this.page.locator(".count-items .count").first().waitFor({
      state: "attached",
      timeout: readyTimeoutMs,
    });
    await this.page.locator("#SearchGrid li.SearchBoxclass, #SearchGrid li").first().waitFor({
      state: "attached",
      timeout: readyTimeoutMs,
    });
  }

  async expectResultVisible(resultLabel) {
    await this.resultItems().filter({ hasText: resultLabel }).first().waitFor({
      state: "visible",
    });
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

  async clickFacetLink(groupLabel, valueLabel) {
    await clickMarked(this.facetLink(groupLabel, valueLabel));
    await this.page.waitForLoadState("domcontentloaded", { timeout: navigationTimeoutMs }).catch(() => {});
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
}

module.exports = {
  OntologyHubTermsPage,
};
