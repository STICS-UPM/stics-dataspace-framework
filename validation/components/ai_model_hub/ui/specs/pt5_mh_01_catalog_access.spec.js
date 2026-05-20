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
  await expect(catalogPage.requestButton).toBeEnabled();
  await expect(catalogPage.errorAlert).toHaveCount(0);

  await catalogPage.openRequestDialog();
  await expect(catalogPage.counterPartyAddressInput).toBeVisible();
  await expect(catalogPage.counterPartyIdInput).toBeVisible();
  await catalogPage.fillRequestDialog(aiModelHubRuntime.providerProtocolUrl, aiModelHubRuntime.providerConnectorId);
  await captureStep(page, "pt5-mh-01-catalog-request-dialog");

  await attachJson("pt5-mh-01-state", {
    route: aiModelHubRuntime.catalogPath,
    dataspace: aiModelHubRuntime.dataspace,
    adapterName: aiModelHubRuntime.adapterName,
    providerConnectorId: aiModelHubRuntime.providerConnectorId,
    providerProtocolUrl: aiModelHubRuntime.providerProtocolUrl,
    requestSurfaceReady: true,
    catalogCardCount: await catalogPage.catalogCards.count(),
  });
});
