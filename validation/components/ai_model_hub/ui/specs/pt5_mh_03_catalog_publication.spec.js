const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../auth");
const { createPublishedProviderModelAsset, waitForConsumerCatalogAsset } = require("../bootstrap");
const { CatalogPage } = require("../pages/catalog.page");

test("PT5-MH-03: provider publication becomes visible through the consumer catalog UI", async ({
  page,
  request,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const catalogPage = new CatalogPage(page, aiModelHubRuntime);
  const suffix = `${Date.now()}`;
  const assetId = `pt5-mh-03-model-${suffix}`;
  const assetName = `PT5 MH 03 Model ${suffix}`;
  const policyId = `policy-pt5-mh-03-${suffix}`;
  const contractDefinitionId = `contract-pt5-mh-03-${suffix}`;
  const baseUrl = `http://pt5-mh-03.local/assets/${assetId}`;

  const publicationState = await createPublishedProviderModelAsset(request, aiModelHubRuntime, {
    assetId,
    assetName,
    policyId,
    contractDefinitionId,
    baseUrl,
    description: "PT5-MH-03 publication slice created by Playwright for catalog visibility checks.",
    version: aiModelHubRuntime.modelVersion,
    task: "text-classification",
    library: "xgboost",
  });
  const catalogVisibility = await waitForConsumerCatalogAsset(request, aiModelHubRuntime, assetId);

  const connectorAuthorization = await attachManagementAuthorizationRoutes(page, aiModelHubRuntime);

  await catalogPage.goto();
  await catalogPage.waitUntilReady();
  await captureStep(page, "pt5-mh-03-before-catalog-request");

  await catalogPage.requestCatalogManually(aiModelHubRuntime.providerProtocolUrl);

  const publishedCard = await catalogPage.findCatalogCardAcrossPages(assetId);
  await expect(publishedCard).toBeVisible({ timeout: 20000 });
  await expect(publishedCard).toContainText(/Negotiate/i);
  await expect(publishedCard).toContainText(aiModelHubRuntime.providerConnectorName);
  await captureStep(page, "pt5-mh-03-published-model-visible");

  await attachJson("pt5-mh-03-publication", {
    route: aiModelHubRuntime.catalogPath,
    consumerConnector: aiModelHubRuntime.consumerConnectorName,
    providerConnector: aiModelHubRuntime.providerConnectorName,
    providerProtocolUrl: aiModelHubRuntime.providerProtocolUrl,
    publicationState,
    catalogVisibility,
    visibleCardText: (await publishedCard.innerText()).trim(),
    catalogCardCount: await catalogPage.catalogCards.count(),
    authorizedConnectors: Object.keys(connectorAuthorization),
  });
});
