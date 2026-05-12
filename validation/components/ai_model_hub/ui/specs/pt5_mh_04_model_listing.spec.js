const { test, expect } = require("../fixtures");
const { MlAssetsPage } = require("../pages/ml_assets.page");

test("PT5-MH-04: model listing view renders the discovery shell", async ({
  page,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const assetsPage = new MlAssetsPage(page, aiModelHubRuntime);

  await assetsPage.goto();
  await assetsPage.waitUntilReady();
  await captureStep(page, "pt5-mh-04-ml-assets");

  await expect(page).toHaveURL(new RegExp(`${aiModelHubRuntime.mlAssetsPath}$`));
  await expect(assetsPage.searchInput).toBeVisible();
  await expect(assetsPage.filterHeading).toBeVisible();
  await expect(assetsPage.errorAlert).toHaveCount(0);

  await attachJson("pt5-mh-04-state", {
    route: aiModelHubRuntime.mlAssetsPath,
    assetCardCount: await assetsPage.assetCards.count(),
    filterOptionCount: await assetsPage.filterCheckboxes.count(),
    noResultsVisible: await assetsPage.noResultsMessage.first().isVisible().catch(() => false),
  });
});
