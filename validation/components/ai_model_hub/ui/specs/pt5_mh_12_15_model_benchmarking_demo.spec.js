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
const BASELINE_A = "model-flares-reliability-baseline-a";
const BASELINE_B = "model-flares-reliability-baseline-b";

function demoEnabled() {
  return (process.env[DEMO_ENV] || "").trim().toLowerCase() === "1";
}

function stablePayloadKey(payload) {
  return JSON.stringify({
    tag_text: payload?.tag_text || "",
    text: payload?.text || "",
    w1h_label: payload?.w1h_label || "",
  });
}

function buildExpectedByPayload(rows) {
  const expectedByPayload = new Map();
  for (const row of rows) {
    expectedByPayload.set(stablePayloadKey(row.input), {
      recordId: row.record_id,
      expectedLabel: row.expected_label,
    });
  }
  return expectedByPayload;
}

function predictionFor(assetId, expected) {
  if (assetId === BASELINE_B && [106, 534].includes(expected.recordId)) {
    return "confiable";
  }
  return expected.expectedLabel;
}

async function installBenchmarkInferDemoRoute(page, runtime, rows) {
  const expectedByPayload = buildExpectedByPayload(rows);
  const inferenceCalls = [];
  const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Content-Type": "application/json",
  };

  await page.route("**/api/infer", async (route) => {
    const request = route.request();
    if (request.method().toUpperCase() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: corsHeaders,
        body: "",
      });
      return;
    }

    const body = request.postDataJSON();
    const assetId = String(body?.assetId || "");
    const payload = body?.payload || {};
    const expected = expectedByPayload.get(stablePayloadKey(payload));

    if (!expected) {
      await route.fulfill({
        status: 422,
        headers: corsHeaders,
        body: JSON.stringify({
          error: "Unknown FLARES demo payload",
          assetId,
        }),
      });
      return;
    }

    const label = predictionFor(assetId, expected);
    inferenceCalls.push({
      assetId,
      recordId: expected.recordId,
      expectedLabel: expected.expectedLabel,
      predictedLabel: label,
      path: body?.path || "/infer",
      endpoint: `${runtime.consumerDefaultUrl}/infer`,
    });

    await route.fulfill({
      status: 200,
      headers: corsHeaders,
      body: JSON.stringify({
        result: {
          label,
        },
        model: assetId,
        demo: "ai-model-hub-benchmarking-ui",
      }),
    });
  });

  return inferenceCalls;
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
  const inferenceCalls = await installBenchmarkInferDemoRoute(page, aiModelHubRuntime, benchmarkRows);
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
  const benchmarkingPage = new ModelBenchmarkingPage(page, aiModelHubRuntime);

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
  await captureStep(page, `${stepPrefix}-benchmark-configured`);

  if (runBenchmark) {
    await benchmarkingPage.runBenchmark();
    await benchmarkingPage.waitForBenchmarkResults(linguisticModels.models.length);
    await captureStep(page, `${stepPrefix}-benchmark-results`);
  }

  const resultRowsText = runBenchmark ? await benchmarkingPage.resultRowsText() : [];
  await attachJson(`${stepPrefix}-benchmarking-demo`, {
    demoMode: "playwright-ui-with-controlled-infer-route",
    inferenceEndpointMockedInBrowser: `${aiModelHubRuntime.consumerDefaultUrl}/infer`,
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
    inferenceCalls,
    resultRowsText,
    authorizedConnectors: Object.keys(authorizedConnectors),
  });

  return {
    benchmarkingPage,
    fixture,
    linguisticModels,
    localBenchmarkDataset,
    inferenceCalls,
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

    expect(state.linguisticModels.models).toHaveLength(2);
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

    const expectedCalls = state.linguisticModels.models.length * state.linguisticModels.benchmarkRows.length;
    expect(state.inferenceCalls).toHaveLength(expectedCalls);
    expect(new Set(state.inferenceCalls.map((call) => call.recordId)).size).toBe(
      state.linguisticModels.benchmarkRows.length,
    );
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
    expect(state.resultRowsText.join("\n")).toContain("FLARES Reliability Baseline A");
    expect(state.resultRowsText.join("\n")).toContain("FLARES Reliability Baseline B");
  });
});
