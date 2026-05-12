const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../auth");
const {
  createPublishedProviderModelAsset,
  waitForConsumerAgreement,
  waitForConsumerCatalogAsset,
} = require("../bootstrap");
const { CatalogPage } = require("../pages/catalog.page");
const { clickMarked } = require("../support/live-marker");

test("PT5-MH-08: contract negotiation from catalog registers an agreement in the consumer connector", async ({
  page,
  request,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const catalogPage = new CatalogPage(page, aiModelHubRuntime);
  const suffix = `${Date.now()}`;
  const assetId = `pt5-mh-08-model-${suffix}`;
  const assetName = `PT5 MH 08 Model ${suffix}`;
  const policyId = `policy-pt5-mh-08-${suffix}`;
  const contractDefinitionId = `contract-pt5-mh-08-${suffix}`;
  const baseUrl = `http://pt5-mh-08.local/assets/${assetId}`;

  const publicationState = await createPublishedProviderModelAsset(request, aiModelHubRuntime, {
    assetId,
    assetName,
    policyId,
    contractDefinitionId,
    baseUrl,
    description: "PT5-MH-08 published model prepared for consumer-side contract negotiation checks.",
    version: aiModelHubRuntime.modelVersion,
    task: "text-classification",
    library: "xgboost",
  });
  const catalogVisibility = await waitForConsumerCatalogAsset(request, aiModelHubRuntime, assetId);

  const connectorAuthorization = await attachManagementAuthorizationRoutes(page, aiModelHubRuntime);

  await catalogPage.goto();
  await catalogPage.waitUntilReady();
  await catalogPage.requestCatalogManually(aiModelHubRuntime.providerProtocolUrl);

  const publishedCard = await catalogPage.findCatalogCardAcrossPages(assetId);
  await expect(publishedCard).toBeVisible({ timeout: 20000 });
  await expect(catalogPage.negotiateButtonForCard(publishedCard)).toBeVisible();
  const visibleCardText = (await publishedCard.innerText()).trim();
  await captureStep(page, "pt5-mh-08-catalog-card-visible");

  await catalogPage.openNegotiationForCard(publishedCard);
  await expect(catalogPage.negotiationDialog).toContainText("Catalog Dataset");
  await expect(catalogPage.negotiationDialog).toContainText(assetId);
  await catalogPage.selectFirstOffer();
  await captureStep(page, "pt5-mh-08-offer-selected");

  await catalogPage.startNegotiation();
  await expect(catalogPage.progressTitle).toBeVisible({ timeout: 10000 });
  await expect(catalogPage.negotiationDialog).toContainText("FINALIZED", { timeout: 30000 });
  await expect(catalogPage.goToContractsButton).toBeVisible({ timeout: 30000 });
  await captureStep(page, "pt5-mh-08-negotiation-finalized");

  const agreementState = await waitForConsumerAgreement(request, aiModelHubRuntime, assetId, 20, 1000);

  await clickMarked(catalogPage.goToContractsButton);
  await expect(page).toHaveURL(new RegExp(`${aiModelHubRuntime.contractsPath}$`));
  await captureStep(page, "pt5-mh-08-contracts-route");

  await attachJson("pt5-mh-08-contract-negotiation", {
    route: aiModelHubRuntime.catalogPath,
    contractsRoute: aiModelHubRuntime.contractsPath,
    consumerConnector: aiModelHubRuntime.consumerConnectorName,
    providerConnector: aiModelHubRuntime.providerConnectorName,
    publicationState,
    catalogVisibility,
    agreementState,
    visibleCardText,
    authorizedConnectors: Object.keys(connectorAuthorization),
  });
});
