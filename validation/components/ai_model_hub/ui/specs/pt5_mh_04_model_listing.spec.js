const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../auth");
const { createLocalConsumerModelAsset, waitForLocalConsumerAsset } = require("../bootstrap");
const { MlAssetsPage } = require("../pages/ml_assets.page");

test("PT5-MH-04: model listing view renders a controlled model card", async ({
  page,
  request,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const assetsPage = new MlAssetsPage(page, aiModelHubRuntime);
  const suffix = `${Date.now()}`;
  const assetId = `pt5-mh-04-model-${suffix}`;
  const assetName = `PT5 MH 04 Listed Model ${suffix}`;
  const localAssetState = await createLocalConsumerModelAsset(request, aiModelHubRuntime, {
    assetId,
    assetName,
    baseUrl: `http://pt5-mh-04.local/models/${suffix}`,
    description: "PT5-MH-04 controlled local model for listing validation.",
    version: "v1.0.0",
    task: "text-classification",
    library: "scikit-learn",
    keywords: ["pt5-mh-04", "playwright", "listing"],
  });
  const managementVisibility = await waitForLocalConsumerAsset(request, aiModelHubRuntime, assetId);
  const connectorAuthorization = await attachManagementAuthorizationRoutes(page, aiModelHubRuntime);

  await expect(async () => {
    await assetsPage.goto(aiModelHubRuntime.consumerConnectorName);
    await assetsPage.waitUntilReady();
    // The ML Assets page can briefly render an empty state before connector data is hydrated.
    await expect(assetsPage.assetCards.first()).toBeVisible({ timeout: 30000 });
    await assetsPage.search(assetName);
    await assetsPage.expectCardVisible(assetName);
  }).toPass({
    timeout: 90000,
    intervals: [1000, 2000, 5000],
  });
  await captureStep(page, "pt5-mh-04-listed-model");

  await expect(page).toHaveURL(new RegExp(`${aiModelHubRuntime.mlAssetsPath}$`));
  await expect(assetsPage.searchInput).toBeVisible();
  await expect(assetsPage.filterHeading).toBeVisible();
  await expect(assetsPage.errorAlert).toHaveCount(0);

  await attachJson("pt5-mh-04-state", {
    route: aiModelHubRuntime.mlAssetsPath,
    localAssetState,
    managementVisibility,
    selectedConnector: await assetsPage.connectorSelect
      .locator("option:checked")
      .textContent({ timeout: 1000 })
      .catch(() => null),
    authorizedConnectors: Object.keys(connectorAuthorization),
    assetCardCount: await assetsPage.assetCards.count(),
    filterOptionCount: await assetsPage.filterCheckboxes.count(),
    noResultsVisible: await assetsPage.noResultsMessage.first().isVisible().catch(() => false),
  });
});
