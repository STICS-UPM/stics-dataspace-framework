const { test } = require("../../ui/fixtures");
const { OntologyHubHomePage } = require("../../ui/pages/home.page");
const { OntologyHubApiDocsPage } = require("../../ui/pages/api-docs.page");

test("PT5-OH-15: public UI and API documentation are published together", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  const homePage = new OntologyHubHomePage(page);
  const apiDocsPage = new OntologyHubApiDocsPage(page);

  await homePage.goto(ontologyHubRuntime.baseUrl);
  await homePage.expectReady();
  await homePage.navLink("Vocabs").waitFor({ state: "visible" });
  await homePage.navLink("SPARQL/Dump").waitFor({ state: "visible" });
  await captureStep(page, "01-home-page");

  await apiDocsPage.goto(ontologyHubRuntime.baseUrl);
  await apiDocsPage.expectReady();
  await captureStep(page, "02-api-docs");

  await attachJson("pt5-oh-15-report", {
    homeUrl: `${ontologyHubRuntime.baseUrl}/dataset`,
    apiDocsUrl: `${ontologyHubRuntime.baseUrl}/dataset/api`,
  });
});
