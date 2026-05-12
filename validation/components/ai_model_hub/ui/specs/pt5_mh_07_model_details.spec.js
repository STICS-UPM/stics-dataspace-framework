const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../auth");
const { createLocalConsumerModelAsset, waitForLocalConsumerAsset } = require("../bootstrap");
const { MlAssetsPage } = require("../pages/ml_assets.page");
const { clickMarked, fillMarked } = require("../support/live-marker");

test("PT5-MH-07: model details view exposes functional and technical metadata", async ({
  page,
  request,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const assetsPage = new MlAssetsPage(page, aiModelHubRuntime);
  const suffix = `${Date.now()}`;
  const assetId = `pt5-mh-07-model-${suffix}`;
  const assetName = `PT5 MH 07 Model ${suffix}`;
  const description = "PT5-MH-07 local model prepared for detailed metadata visualization checks.";
  const baseUrl = `http://pt5-mh-07.local/assets/${assetId}`;
  const version = "v1.2.3";
  const task = "text-classification";
  const library = "xgboost";
  const keywords = ["pt5-mh-07", "playwright", "details"];

  const localAssetState = await createLocalConsumerModelAsset(request, aiModelHubRuntime, {
    assetId,
    assetName,
    baseUrl,
    description,
    version,
    task,
    library,
    keywords,
  });
  const managementVisibility = await waitForLocalConsumerAsset(request, aiModelHubRuntime, assetId);

  const connectorAuthorization = await attachManagementAuthorizationRoutes(page, aiModelHubRuntime);

  await assetsPage.goto();
  await assetsPage.waitUntilReady();
  await fillMarked(assetsPage.searchInput, assetName);

  const card = assetsPage.cardByText(assetName);
  await expect(card).toBeVisible({ timeout: 15000 });
  await captureStep(page, "pt5-mh-07-card-visible");

  await assetsPage.openDetailsForCard(card);
  await expect(assetsPage.detailsDialogTitle).toContainText(assetName);
  await expect(assetsPage.detailsDialogAssetId).toContainText(assetId);
  await expect(assetsPage.detailsDialog).toContainText(`Version: ${version}`);
  await expect(assetsPage.detailsDialog).toContainText("Source: Local Asset");
  await expect(assetsPage.detailsDialog).toContainText(`Content Type: ${aiModelHubRuntime.modelContentType}`);
  await expect(assetsPage.detailsDialog).toContainText("Storage: HttpData");
  await expect(assetsPage.detailsDialog).toContainText(`Tasks: ${task}`);
  await expect(assetsPage.detailsDialog).toContainText(`Libraries: ${library}`);
  await expect(assetsPage.detailsDialog).toContainText(keywords.join(", "));

  await clickMarked(assetsPage.rawPayloadTab);
  await expect(assetsPage.detailsDialog).toContainText(assetId);
  await expect(assetsPage.detailsDialog).toContainText(version);
  await expect(assetsPage.detailsDialog).toContainText("https://pionera.ai/edc/daimo#pipeline_tag");
  await captureStep(page, "pt5-mh-07-details-modal");

  await attachJson("pt5-mh-07-details", {
    route: aiModelHubRuntime.mlAssetsPath,
    connector: aiModelHubRuntime.consumerConnectorName,
    localAssetState,
    managementVisibility,
    authorizedConnectors: Object.keys(connectorAuthorization),
  });
});
