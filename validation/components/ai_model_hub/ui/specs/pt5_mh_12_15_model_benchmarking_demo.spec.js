const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../auth");
const { ModelBenchmarkingPage } = require("../pages/model_benchmarking.page");
const {
  buildFlaresBenchmarkRows,
  ensureFlaresLinguisticModelsPublished,
  ensureLocalFlaresBenchmarkDatasetPublished,
  loadFlaresDataset,
} = require("../../functional/linguistic/bootstrap");

const DEMO_ENV = "AI_MODEL_HUB_ENABLE_BENCHMARKING_UI_DEMO";

function demoEnabled() {
  return (process.env[DEMO_ENV] || "").trim().toLowerCase() === "1";
}

function commonModelSearchText(models) {
  return "FLARES Reliability";
}

async function prepareBenchmarkingDemo({
  page,
  request,
  aiModelHubRuntime,
  captureStep,
  attachJson,
  runBenchmark = false,
  stepPrefix,
}) {
  const fixture = loadFlaresDataset();
  const benchmarkRows = buildFlaresBenchmarkRows(fixture);
  const authorizedConnectors = await attachManagementAuthorizationRoutes(page, aiModelHubRuntime);
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
  const benchmarkingPage = new ModelBenchmarkingPage(page, aiModelHubRuntime);

  await benchmarkingPage.goto(aiModelHubRuntime.consumerConnectorName);
  await benchmarkingPage.waitUntilReady();

  await benchmarkingPage.selectCompatibleModelsBySearch(
    commonModelSearchText(linguisticModels.models),
    linguisticModels.models.map((model) => model.assetName),
  );

  await benchmarkingPage.datasetSearchInput.fill(localBenchmarkDataset.assetId);
  await benchmarkingPage.selectDataspaceDatasetByText(localBenchmarkDataset.assetId);
  await benchmarkingPage.loadSelectedDataset();
  await expect(benchmarkingPage.inputPathInput).toHaveValue("request");
  await expect(benchmarkingPage.expectedPathInput).toHaveValue("expected_label");
  await expect(benchmarkingPage.predictionPathInput).toHaveValue("0.Reliability_Label");
  await captureStep(page, `${stepPrefix}-benchmark-configured`);

  if (runBenchmark) {
    await benchmarkingPage.runBenchmark();
    await benchmarkingPage.waitForBenchmarkResults(linguisticModels.models.length);
    await captureStep(page, `${stepPrefix}-benchmark-results`);
  }

  const resultRowsText = runBenchmark ? await benchmarkingPage.resultRowsText() : [];
  await attachJson(`${stepPrefix}-benchmarking-demo`, {
    demoMode: "playwright-ui-with-real-flares-model-server",
    modelServerBaseUrl: aiModelHubRuntime.modelServerBaseUrl,
    route: aiModelHubRuntime.modelBenchmarkingPath,
    selectedModels: linguisticModels.models.map((model) => ({
      assetId: model.assetId,
      assetName: model.assetName,
      created: model.created,
      existing: model.existing,
    })),
    localBenchmarkDataset,
    mapping: linguisticModels.benchmarkMapping,
    datasetRows: linguisticModels.benchmarkRows.length,
    expectedClasses: fixture.expectedOutputs.subtask2_trial_sample.classDistribution,
    resultRowsText,
    authorizedConnectors: Object.keys(authorizedConnectors),
  });

  return {
    benchmarkingPage,
    fixture,
    linguisticModels,
    localBenchmarkDataset,
    resultRowsText,
  };
}

test.describe("AI Model Hub benchmarking visual demo", () => {
  test.beforeEach(() => {
    test.skip(!demoEnabled(), `Set ${DEMO_ENV}=1 to run the auditor-facing benchmarking UI demo.`);
  });

  test("PT5-MH-12: benchmarking UI selects multiple FLARES models", async ({
    page,
    request,
    aiModelHubRuntime,
    captureStep,
    attachJson,
  }) => {
    const state = await prepareBenchmarkingDemo({
      page,
      request,
      aiModelHubRuntime,
      captureStep,
      attachJson,
      stepPrefix: "pt5-mh-12",
    });

    expect(state.linguisticModels.models).toHaveLength(3);
    await expect(state.benchmarkingPage.runBenchmarkButton).toBeVisible();
    await expect(state.benchmarkingPage.runBenchmarkButton).toBeEnabled();
  });

  test("PT5-MH-13: benchmarking UI executes selected models with the same input", async ({
    page,
    request,
    aiModelHubRuntime,
    captureStep,
    attachJson,
  }) => {
    const state = await prepareBenchmarkingDemo({
      page,
      request,
      aiModelHubRuntime,
      captureStep,
      attachJson,
      runBenchmark: true,
      stepPrefix: "pt5-mh-13",
    });

    await expect(state.benchmarkingPage.resultsRows).toHaveCount(state.linguisticModels.models.length);
    const rowsText = state.resultRowsText.join("\n");
    for (const model of state.linguisticModels.models) {
      expect(rowsText).toContain(model.assetName);
    }
  });

  test("PT5-MH-14: benchmarking UI renders calculated comparison metrics", async ({
    page,
    request,
    aiModelHubRuntime,
    captureStep,
    attachJson,
  }) => {
    const state = await prepareBenchmarkingDemo({
      page,
      request,
      aiModelHubRuntime,
      captureStep,
      attachJson,
      runBenchmark: true,
      stepPrefix: "pt5-mh-14",
    });

    await expect(state.benchmarkingPage.bestModelSummary).toContainText(/Score:/i);
    await expect(state.benchmarkingPage.resultsTable).toContainText(/Success %/i);
    await expect(state.benchmarkingPage.resultsTable).toContainText(/Accuracy %/i);
    await expect(state.benchmarkingPage.resultsTable).toContainText(/Score/i);
  });

  test("PT5-MH-15: benchmarking UI shows comparative table and best model summary", async ({
    page,
    request,
    aiModelHubRuntime,
    captureStep,
    attachJson,
  }) => {
    const state = await prepareBenchmarkingDemo({
      page,
      request,
      aiModelHubRuntime,
      captureStep,
      attachJson,
      runBenchmark: true,
      stepPrefix: "pt5-mh-15",
    });

    await expect(state.benchmarkingPage.bestModelSummary).toContainText(/Best Model:/i);
    await expect(state.benchmarkingPage.resultsRows).toHaveCount(state.linguisticModels.models.length);
    const rowsText = state.resultRowsText.join("\n");
    for (const model of state.linguisticModels.models) {
      expect(rowsText).toContain(model.assetName);
    }
  });
});
