const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../auth");
const { waitForLocalProviderAsset } = require("../bootstrap");
const { AssetsPage } = require("../pages/assets.page");

test("PT5-MH-02: provider can register a local model asset with valid metadata", async ({
  page,
  request,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const assetsPage = new AssetsPage(page, aiModelHubRuntime);
  const suffix = `${Date.now()}`;
  const assetId = `pt5-mh-02-model-${suffix}`;
  const assetName = `PT5 MH 02 Model ${suffix}`;
  const baseUrl = `http://pt5-mh-02.local/assets/${assetId}`;
  const connectorAuthorization = await attachManagementAuthorizationRoutes(page, aiModelHubRuntime);

  await assetsPage.goto();
  await assetsPage.waitUntilReady();
  await assetsPage.switchToConnector(aiModelHubRuntime.providerConnectorName);

  const createDialog = await assetsPage.openCreateAssetDialog();
  await createDialog.fillCommonFields({
    id: assetId,
    name: assetName,
    contentType: aiModelHubRuntime.modelContentType,
  });
  await createDialog.selectFirstDataType();
  await createDialog.fillBaseUrl(baseUrl);
  await createDialog.enableMlMetadataHelper();
  await createDialog.fillMlMetadata({
    description: aiModelHubRuntime.modelDescription,
    version: aiModelHubRuntime.modelVersion,
    assetKind: "model",
    task: "text-classification",
  });
  await createDialog.addProperty("version", aiModelHubRuntime.modelVersion);
  await createDialog.addProperty("shortDescription", aiModelHubRuntime.modelDescription);
  await createDialog.addProperty("assetType", "machineLearning");
  await createDialog.addProperty(
    "http://purl.org/dc/terms/description",
    aiModelHubRuntime.modelDescription,
  );
  await createDialog.addProperty(
    "http://www.w3.org/ns/dcat#keyword",
    JSON.stringify(["machine-learning", "pt5-mh-02", "playwright"]),
  );

  await expect(createDialog.createAssetButton).toBeEnabled();
  await expect(createDialog.errorLabel).toHaveCount(0);
  await captureStep(page, "pt5-mh-02-before-submit");

  await createDialog.submit();

  await expect(createDialog.root).toBeHidden({ timeout: 15000 });
  await expect(assetsPage.successAlert.filter({ hasText: /created successfully/i })).toBeVisible({
    timeout: 15000,
  });
  await expect(assetsPage.errorAlert).toHaveCount(0);
  const managementVisibility = await waitForLocalProviderAsset(request, aiModelHubRuntime, assetId, 20, 1000);
  const persistedAsset = managementVisibility.asset;

  await expect.soft(persistedAsset['@id'] || persistedAsset.id).toBe(assetId);
  await expect.soft(persistedAsset.properties.name).toBe(assetName);
  await expect.soft(persistedAsset.properties.version).toBe(aiModelHubRuntime.modelVersion);
  await expect.soft(persistedAsset.properties.shortDescription).toBe(aiModelHubRuntime.modelDescription);
  await expect.soft(persistedAsset.properties.assetType).toBe('machineLearning');
  await expect.soft(persistedAsset.properties.contenttype).toBe(aiModelHubRuntime.modelContentType);
  await expect.soft(persistedAsset.properties['daimo:asset_kind']).toBe('model');
  await expect.soft(persistedAsset.properties['daimo:pipeline_tag']).toBe('text-classification');
  await expect
    .soft(persistedAsset.properties['http://www.w3.org/ns/dcat#keyword'] || [])
    .toContain('pt5-mh-02');
  await expect.soft(persistedAsset.dataAddress.type).toBe('HttpData');
  await expect.soft(persistedAsset.dataAddress.baseUrl).toBe(baseUrl);

  await captureStep(page, "pt5-mh-02-created-model");
  await attachJson("pt5-mh-02-state", {
    route: aiModelHubRuntime.assetsPath,
    connector: aiModelHubRuntime.providerConnectorName,
    assetId,
    assetName,
    baseUrl,
    contentType: aiModelHubRuntime.modelContentType,
    mlMetadataEnabled: true,
    managementVisibility,
    authorizedConnectors: Object.keys(connectorAuthorization),
  });
});
