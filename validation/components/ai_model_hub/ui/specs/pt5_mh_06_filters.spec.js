const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../auth");
const { createLocalConsumerModelAsset, waitForLocalConsumerAsset } = require("../bootstrap");
const { MlAssetsPage } = require("../pages/ml_assets.page");

test("PT5-MH-06: model discovery filter shell is available in the ML assets view", async ({
  page,
  request,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const assetsPage = new MlAssetsPage(page, aiModelHubRuntime);
  const suffix = `${Date.now()}`;
  const searchScope = `PT5 MH 06 ${suffix}`;
  const textAsset = {
    assetId: `pt5-mh-06-text-${suffix}`,
    assetName: `${searchScope} Text Classifier`,
    baseUrl: `http://pt5-mh-06.local/text/${suffix}`,
    description: "PT5-MH-06 controlled asset for validating task filter behavior.",
    version: "v1.0.0",
    task: "text-classification",
    library: "xgboost",
    keywords: ["pt5-mh-06", "playwright", "filter", "text"],
  };
  const tabularAsset = {
    assetId: `pt5-mh-06-tabular-${suffix}`,
    assetName: `${searchScope} Tabular Classifier`,
    baseUrl: `http://pt5-mh-06.local/tabular/${suffix}`,
    description: "PT5-MH-06 controlled asset that must be excluded by the text task filter.",
    version: "v1.0.0",
    task: "tabular-classification",
    library: "scikit-learn",
    keywords: ["pt5-mh-06", "playwright", "filter", "tabular"],
  };

  const createdAssets = [];
  for (const asset of [textAsset, tabularAsset]) {
    createdAssets.push(await createLocalConsumerModelAsset(request, aiModelHubRuntime, asset));
    await waitForLocalConsumerAsset(request, aiModelHubRuntime, asset.assetId);
  }
  const connectorAuthorization = await attachManagementAuthorizationRoutes(page, aiModelHubRuntime);

  await assetsPage.goto(aiModelHubRuntime.consumerConnectorName);
  await assetsPage.waitUntilReady();
  await assetsPage.search(searchScope);

  await expect(assetsPage.filterHeading).toBeVisible();
  await expect(assetsPage.errorAlert).toHaveCount(0);
  await assetsPage.expectCardVisible(textAsset.assetName);
  await assetsPage.expectCardVisible(tabularAsset.assetName);

  const filterCount = await assetsPage.filterCheckboxes.count();
  await assetsPage.applyFilter("Tasks", textAsset.task);
  await assetsPage.expectCardVisible(textAsset.assetName);
  await assetsPage.expectCardHidden(tabularAsset.assetName);
  await expect(assetsPage.clearFiltersButton).toBeVisible();

  await captureStep(page, "pt5-mh-06-filters");
  await attachJson("pt5-mh-06-state", {
    searchScope,
    createdAssets,
    selectedTask: textAsset.task,
    excludedTask: tabularAsset.task,
    authorizedConnectors: Object.keys(connectorAuthorization),
    filterOptionCount: filterCount,
    clearButtonVisible: await assetsPage.clearFiltersButton.isVisible().catch(() => false),
  });
});
