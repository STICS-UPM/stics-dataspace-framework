const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../auth");
const { createLocalConsumerModelAsset, waitForLocalConsumerAsset } = require("../bootstrap");
const { MlAssetsPage } = require("../pages/ml_assets.page");

test("PT5-MH-05: model discovery search returns the controlled matching model", async ({
  page,
  request,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const assetsPage = new MlAssetsPage(page, aiModelHubRuntime);
  const suffix = `${Date.now()}`;
  const searchToken = `pt5-mh-05-needle-${suffix}`;
  const matchingAsset = {
    assetId: `pt5-mh-05-match-${suffix}`,
    assetName: `PT5 MH 05 Search Target ${searchToken}`,
    baseUrl: `http://pt5-mh-05.local/match/${suffix}`,
    description: "PT5-MH-05 controlled asset that should be returned by free text search.",
    version: "v1.0.0",
    task: "text-classification",
    library: "transformers",
    keywords: ["pt5-mh-05", "playwright", "search", searchToken],
  };
  const controlAsset = {
    assetId: `pt5-mh-05-control-${suffix}`,
    assetName: `PT5 MH 05 Search Control ${suffix}`,
    baseUrl: `http://pt5-mh-05.local/control/${suffix}`,
    description: "PT5-MH-05 controlled asset that should be excluded by the unique search token.",
    version: "v1.0.0",
    task: "tabular-classification",
    library: "scikit-learn",
    keywords: ["pt5-mh-05", "playwright", "control"],
  };
  const createdAssets = [];
  for (const asset of [matchingAsset, controlAsset]) {
    createdAssets.push(await createLocalConsumerModelAsset(request, aiModelHubRuntime, asset));
    await waitForLocalConsumerAsset(request, aiModelHubRuntime, asset.assetId);
  }
  const connectorAuthorization = await attachManagementAuthorizationRoutes(page, aiModelHubRuntime);

  await expect(async () => {
    await assetsPage.goto();
    await assetsPage.waitUntilReady();
    await assetsPage.search(searchToken);
    await assetsPage.expectCardVisible(matchingAsset.assetName);
    await assetsPage.expectCardHidden(controlAsset.assetName);
  }).toPass({
    timeout: 90000,
    intervals: [1000, 2000, 5000],
  });

  await captureStep(page, "pt5-mh-05-search");

  await expect(assetsPage.searchInput).toHaveValue(searchToken);
  await expect(assetsPage.errorAlert).toHaveCount(0);

  await attachJson("pt5-mh-05-state", {
    searchToken,
    createdAssets,
    matchingAssetId: matchingAsset.assetId,
    excludedAssetId: controlAsset.assetId,
    authorizedConnectors: Object.keys(connectorAuthorization),
    assetCardCount: await assetsPage.assetCards.count(),
  });
});
