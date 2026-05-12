const { test, expect } = require("../fixtures");
const { CatalogPage } = require("../pages/catalog.page");

test("PT5-MH-01: model catalog view is reachable from the public UI", async ({
  page,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const catalogPage = new CatalogPage(page, aiModelHubRuntime);

  await catalogPage.goto();
  await catalogPage.waitUntilReady();
  await captureStep(page, "pt5-mh-01-catalog");

  await expect(page).toHaveURL(new RegExp(`${aiModelHubRuntime.catalogPath}$`));
  await expect(catalogPage.root).toBeVisible();
  await expect(catalogPage.requestButton).toContainText(aiModelHubRuntime.requestButtonLabel);
  await expect(catalogPage.errorAlert).toHaveCount(0);

  await attachJson("pt5-mh-01-state", {
    route: aiModelHubRuntime.catalogPath,
    catalogCardCount: await catalogPage.catalogCards.count(),
  });
});
