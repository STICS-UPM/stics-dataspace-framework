const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../../ui/auth");
const { CatalogPage } = require("../../ui/pages/catalog.page");
const { ModelBenchmarkingPage } = require("../../ui/pages/model_benchmarking.page");
const {
  ensureFlaresMiniPublished,
  ensureFlaresLinguisticModelsPublished,
  ensureLocalFlaresBenchmarkDatasetPublished,
  loadFlaresMiniFixture,
  probeConsumerInferEndpoint,
  waitForFlaresMiniAgreement,
  waitForFlaresMiniCatalogVisibility,
} = require("../linguistic/bootstrap");

const FUNCTIONAL_ENV = "AI_MODEL_HUB_ENABLE_FUNCTIONAL_VALIDATION";

test.describe("MH-LING-01 scaffold", () => {
  test("MH-LING-01: FLARES-mini is published, discovered and negotiated on demand for the linguistic validation flow", async ({
    page,
    request,
    aiModelHubRuntime,
    captureStep,
    attachJson,
  }) => {
    test.skip(
      (process.env[FUNCTIONAL_ENV] || "").trim().toLowerCase() !== "1",
      "AI Model Hub functional suites remain opt-in until Phase 3 matures.",
    );

    const catalogPage = new CatalogPage(page, aiModelHubRuntime);
    const benchmarkingPage = new ModelBenchmarkingPage(page, aiModelHubRuntime);
    const fixture = loadFlaresMiniFixture();
    const publication = await ensureFlaresMiniPublished(request, aiModelHubRuntime);
    const catalogVisibility = await waitForFlaresMiniCatalogVisibility(
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
    await expect(catalogPage.negotiationDialog).toContainText("FINALIZED", { timeout: 30000 });
    await expect(catalogPage.goToContractsButton).toBeVisible({ timeout: 30000 });
    await captureStep(page, "mh-ling-01-flares-negotiation-finalized");

    const agreementState = await waitForFlaresMiniAgreement(
      request,
      aiModelHubRuntime,
      publication.assetId,
    );

    await catalogPage.goToContractsButton.click();
    await expect(page).toHaveURL(new RegExp(`${aiModelHubRuntime.contractsPath}$`));
    await captureStep(page, "mh-ling-01-flares-contracts-route");

    await benchmarkingPage.goto();
    await benchmarkingPage.waitUntilReady();

    for (const model of linguisticModels.models) {
      await benchmarkingPage.selectModelByText(model.assetName);
    }

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

    await attachJson("flares-mini-metadata", fixture.metadata);
    await attachJson("flares-mini-expected-outputs", fixture.expectedOutputs);
    await attachJson("flares-mini-publication", {
      assetId: publication.assetId,
      created: publication.created,
      existing: publication.existing,
      policyId: publication.policyId || fixture.metadata.assetPublication.policyId,
      contractDefinitionId:
        publication.contractDefinitionId || fixture.metadata.assetPublication.contractDefinitionId,
    });
    await attachJson("flares-mini-local-benchmark-dataset", localBenchmarkDataset);
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

    expect(fixture.metadata.datasetName).toBe("FLARES-mini");
    expect(fixture.subtask2TrialSample.length).toBeGreaterThan(0);
    expect(publication.assetId).toMatch(/^dataset-flares-mini-subtask2/);
    expect(publication.created || publication.existing).toBeTruthy();
    expect(agreementState.assetId).toBe(publication.assetId);
    expect(linguisticModels.models).toHaveLength(2);
    expect(linguisticModels.benchmarkRows).toHaveLength(
      fixture.expectedOutputs.subtask2_trial_sample.recordCount,
    );
    expect(localBenchmarkDataset.assetId).toBe("dataset-flares-mini-local-benchmark");
  });
});
