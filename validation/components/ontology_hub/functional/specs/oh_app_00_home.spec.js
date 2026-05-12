// Excel traceability: Ontology Hub case 1 (Despliegue), adapted to the executable home-page readiness check.
const { test, expect } = require("../../ui/fixtures");
const { expectHealthyPage } = require("../support/excel-flows");

test("OH-APP-00: home page is reachable", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  await page.goto(ontologyHubRuntime.baseUrl, { waitUntil: "domcontentloaded" });
  await expectHealthyPage(page, "Ontology Hub home");

  await expect(page.locator("header nav")).toBeVisible();
  await captureStep(page, "01-home-page");

  await attachJson("oh-app-00-report", {
    url: page.url(),
    baseUrl: ontologyHubRuntime.baseUrl,
  });
});
