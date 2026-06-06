const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../../ui/auth");
const { CatalogPage } = require("../../ui/pages/catalog.page");
const { ContractsPage } = require("../../ui/pages/contracts.page");
const { ModelBenchmarkingPage } = require("../../ui/pages/model_benchmarking.page");
const { clickMarked } = require("../../ui/support/live-marker");
const {
  ensureFlaresDatasetPublished,
  ensureFlaresLinguisticModelsPublished,
  ensureLocalFlaresBenchmarkDatasetPublished,
  loadFlaresDataset,
  probeConsumerInferEndpoint,
  waitForFlaresDatasetAgreement,
  waitForFlaresDatasetCatalogVisibility,
} = require("../linguistic/bootstrap");

const FUNCTIONAL_ENV = "AI_MODEL_HUB_ENABLE_FUNCTIONAL_VALIDATION";

test.describe("MH-LING-01 scaffold", () => {
  test("MH-LING-01: FLARES is published, discovered and negotiated on demand for the linguistic validation flow", async ({
    page,
    request,
    aiModelHubRuntime,
    captureStep,
    attachJson,
  }) => {
    test.setTimeout(4 * 60 * 1000);
    test.skip(
      (process.env[FUNCTIONAL_ENV] || "").trim().toLowerCase() !== "1",
      "AI Model Hub functional validation was disabled explicitly for this execution.",
    );

    const catalogPage = new CatalogPage(page, aiModelHubRuntime);
    const contractsPage = new ContractsPage(page, aiModelHubRuntime);
    const benchmarkingPage = new ModelBenchmarkingPage(page, aiModelHubRuntime);
    const fixture = loadFlaresDataset();
    const publication = await ensureFlaresDatasetPublished(request, aiModelHubRuntime);
    const catalogVisibility = await waitForFlaresDatasetCatalogVisibility(
      request,
      aiModelHubRuntime,
      publication.assetId,
    );
    const linguisticModels = await ensureFlaresLinguisticModelsPublished(
      request,
      aiModelHubRuntime,
      fixture,
    );
    const localBenchmarkDataset = await ensureLocalFlaresBenchmarkDatasetPublished(
      request,
      aiModelHubRuntime,
      fixture,
    );
    const authorizedConnectors = await attachManagementAuthorizationRoutes(page, aiModelHubRuntime);

    await catalogPage.goto();
    await catalogPage.waitUntilReady();
    await catalogPage.requestCatalogManually(aiModelHubRuntime.providerProtocolUrl);

    const publishedCard = await catalogPage.findCatalogCardAcrossPages(publication.assetId);
    await expect(publishedCard).toBeVisible({ timeout: 20000 });
    await expect(publishedCard).toContainText(/Negotiate/i);
    await expect(publishedCard).toContainText(aiModelHubRuntime.providerConnectorName);
    await captureStep(page, "mh-ling-01-flares-visible-in-catalog");

    const visibleCardText = (await publishedCard.innerText()).trim();

    await catalogPage.openNegotiationForCard(publishedCard);
    await expect(catalogPage.negotiationDialog).toContainText(publication.assetId);
    await catalogPage.selectFirstOffer();
    await captureStep(page, "mh-ling-01-flares-offer-selected");

    await catalogPage.startNegotiation();
    await expect(catalogPage.progressTitle).toBeVisible({ timeout: 10000 });
    const agreementState = await waitForFlaresDatasetAgreement(
      request,
      aiModelHubRuntime,
      publication.assetId,
      90,
      1000,
    );

    const goToContractsVisible = await expect(catalogPage.goToContractsButton)
      .toBeVisible({ timeout: 60000 })
      .then(() => true)
      .catch(() => false);
    if (goToContractsVisible) {
      await clickMarked(catalogPage.goToContractsButton);
    } else {
      await captureStep(page, "mh-ling-01-flares-agreement-visible-before-dialog-button");
      await catalogPage.closeDialogIfVisible();
      await contractsPage.goto();
    }
    await expect(page).toHaveURL(new RegExp(`${aiModelHubRuntime.contractsPath}$`));
    await contractsPage.waitUntilReady();
    await contractsPage.search(publication.assetId);
    await expect(contractsPage.cardByAssetId(publication.assetId)).toBeVisible({ timeout: 30000 });
    await captureStep(page, "mh-ling-01-flares-contracts-route");

    await benchmarkingPage.goto();
    await benchmarkingPage.waitUntilReady();

    await benchmarkingPage.selectCompatibleModelsBySearch(
      "model-flares-reliability-baseline",
      linguisticModels.models.map((model) => model.assetName),
    );

    await benchmarkingPage.datasetSearchInput.fill(localBenchmarkDataset.assetId);
    await benchmarkingPage.selectDataspaceDatasetByText(localBenchmarkDataset.assetId);
    await benchmarkingPage.loadSelectedDataset();
    await expect(benchmarkingPage.inputPathInput).toHaveValue("input");
    await expect(benchmarkingPage.expectedPathInput).toHaveValue("expected_label");
    await expect(benchmarkingPage.predictionPathInput).toHaveValue("result.label");
    await expect(benchmarkingPage.statusMessage).toContainText(/Dataset loaded from dataspace/i, {
      timeout: 30000,
    });
    await expect(benchmarkingPage.validateInputButton).toBeVisible();
    await expect(benchmarkingPage.runBenchmarkButton).toBeVisible();
    await captureStep(page, "mh-ling-01-flares-benchmark-ready");

    const inferProbe = await probeConsumerInferEndpoint(request, aiModelHubRuntime);

    await attachJson("flares-metadata", fixture.metadata);
    await attachJson("flares-expected-outputs", fixture.expectedOutputs);
    await attachJson("flares-publication", {
      assetId: publication.assetId,
      created: publication.created,
      existing: publication.existing,
      policyId: publication.policyId || fixture.metadata.assetPublication.policyId,
      contractDefinitionId:
        publication.contractDefinitionId || fixture.metadata.assetPublication.contractDefinitionId,
    });
    await attachJson("flares-local-benchmark-dataset", localBenchmarkDataset);
    await attachJson("mh-ling-01-linguistic-bootstrap", {
      route: aiModelHubRuntime.catalogPath,
      contractsRoute: aiModelHubRuntime.contractsPath,
      benchmarkingRoute: aiModelHubRuntime.modelBenchmarkingPath,
      providerConnector: aiModelHubRuntime.providerConnectorName,
      consumerConnector: aiModelHubRuntime.consumerConnectorName,
      catalogVisibility,
      agreementState,
      visibleCardText,
      inferProbe,
      authorizedConnectors: Object.keys(authorizedConnectors),
      fixtureSummary: {
        trialRecordCount: fixture.subtask2TrialSample.length,
        testRecordCount: fixture.subtask2TestSample.length,
        expectedClasses: fixture.expectedOutputs.subtask2_trial_sample.classDistribution,
      },
      linguisticModels,
      localBenchmarkDataset,
    });

    expect(fixture.metadata.datasetName).toBe("FLARES");
    expect(fixture.subtask2TrialSample.length).toBeGreaterThan(0);
    expect(publication.assetId).toMatch(/^dataset-flares-subtask2/);
    expect(publication.created || publication.existing).toBeTruthy();
    expect(agreementState.assetId).toBe(publication.assetId);
    expect(linguisticModels.models).toHaveLength(2);
    expect(linguisticModels.benchmarkRows).toHaveLength(
      fixture.expectedOutputs.subtask2_trial_sample.recordCount,
    );
    expect(localBenchmarkDataset.assetId).toBe("dataset-flares-local-benchmark");
  });
});
