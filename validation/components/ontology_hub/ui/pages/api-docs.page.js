class OntologyHubApiDocsPage {
  constructor(page) {
    this.page = page;
  }

  async goto(baseUrl) {
    await this.page.goto(`${baseUrl}/dataset/api`, { waitUntil: "domcontentloaded" });
  }

  async expectReady() {
    await this.page.locator("#title").getByText("API", { exact: false }).waitFor({ state: "visible" });
    await this.page.getByText("Search Term API v2", { exact: true }).waitFor({ state: "visible" });
    await this.page.locator("#searchTermv2 .apiPath").waitFor({ state: "visible" });
  }
}

module.exports = {
  OntologyHubApiDocsPage,
};
