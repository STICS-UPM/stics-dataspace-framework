const { test, expect } = require("../fixtures");
const { MlAssetsPage } = require("../pages/ml_assets.page");
const { checkMarked } = require("../support/live-marker");

test("PT5-MH-06: model discovery filter shell is available in the ML assets view", async ({
  page,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const assetsPage = new MlAssetsPage(page, aiModelHubRuntime);

  await assetsPage.goto();
  await assetsPage.waitUntilReady();

  await expect(assetsPage.filterHeading).toBeVisible();
  await expect(assetsPage.errorAlert).toHaveCount(0);

  const filterCount = await assetsPage.filterCheckboxes.count();
  if (filterCount > 0) {
    const firstFilter = assetsPage.filterCheckboxes.first();
    await checkMarked(firstFilter);
    await expect(firstFilter).toBeChecked();
    await expect(assetsPage.clearFiltersButton).toBeVisible();
  }

  await captureStep(page, "pt5-mh-06-filters");
  await attachJson("pt5-mh-06-state", {
    filterOptionCount: filterCount,
    clearButtonVisible:
      filterCount > 0 ? await assetsPage.clearFiltersButton.isVisible().catch(() => false) : false,
  });
});
