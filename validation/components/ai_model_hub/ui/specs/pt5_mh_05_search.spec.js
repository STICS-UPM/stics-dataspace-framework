const { test, expect } = require("../fixtures");
const { MlAssetsPage } = require("../pages/ml_assets.page");
const { fillMarked } = require("../support/live-marker");

test("PT5-MH-05: model discovery search input accepts free text queries", async ({
  page,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const assetsPage = new MlAssetsPage(page, aiModelHubRuntime);

  await assetsPage.goto();
  await assetsPage.waitUntilReady();

  await fillMarked(assetsPage.searchInput, aiModelHubRuntime.searchTerm);
  await captureStep(page, "pt5-mh-05-search");

  await expect(assetsPage.searchInput).toHaveValue(aiModelHubRuntime.searchTerm);
  await expect(assetsPage.errorAlert).toHaveCount(0);

  await attachJson("pt5-mh-05-state", {
    searchTerm: aiModelHubRuntime.searchTerm,
    assetCardCount: await assetsPage.assetCards.count(),
  });
});
