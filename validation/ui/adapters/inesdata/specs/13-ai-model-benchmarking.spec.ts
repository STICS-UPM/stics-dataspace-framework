import { readFile } from "fs/promises";
import { Page } from "@playwright/test";

import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import { clickMarked, setInputFilesMarked } from "../../../shared/utils/live-marker";
import {
  bootstrapProviderNegotiationArtifacts,
  cleanupProviderValidationArtifacts,
} from "../../../shared/utils/provider-bootstrap";
import { EVENTUAL_UI_RETRY_INTERVALS, waitForUiTransition } from "../../../shared/utils/waiting";
import { modelServerUrlForPath } from "../../../shared/utils/model-server-url";

type BenchmarkModelFixture = {
  assetId: string;
  name: string;
  path: string;
  url: string;
  routeKey: string;
};

type AIModelBenchmarkingUiReport = {
  startedAt: string;
  providerConnector: string;
  suffix: string;
  models: BenchmarkModelFixture[];
  validationDataset: {
    fileName: string;
    rows: number;
  };
  outputPreparationChecks: Array<{
    scenario: string;
    expectedMessage: string;
    status: "passed";
  }>;
  suggestedDatasetChecks: Array<{
    scenario: string;
    fileName: string;
    requiredContent: string[];
    status: "passed";
  }>;
  exportChecks: Array<{
    scenario: string;
    fileName: string;
    requiredContent: string[];
    status: "passed";
  }>;
  observerEvidenceChecks: Array<{
    scenario: string;
    benchmarkRunId: string;
    url: string;
    observedEvents: string[];
    status: "passed" | "skipped";
    reason?: string;
  }>;
  linkedCases: string[];
  providerBootstrap: Array<{
    assetId: string;
    policyId: string;
    contractDefinitionId: string;
  }>;
  errorResponses: Array<{ url: string; status: number }>;
  toleratedErrorResponses: Array<{ url: string; status: number }>;
  fatalErrorResponses: Array<{ url: string; status: number }>;
};

const DEFAULT_ECOMMERCE_PATH = "/api/v1/nlp/ecommerce-sentiment";
const DEFAULT_TWITTER_PATH = "/api/v1/nlp/twitter-sentiment";
const TEXT_MODEL_INPUT_FEATURES = [
  {
    name: "text",
    type: "string",
    required: true,
    description: "Text to analyze",
  },
];
const TEXT_MODEL_INPUT_SCHEMA = {
  type: "object",
  required: ["text"],
  properties: {
    text: {
      type: "string",
      description: "Text to analyze",
    },
  },
};
const TEXT_MODEL_INPUT_EXAMPLE = {
  text: "This product is excellent and very useful",
};
const BENCHMARK_DATASET_FILE = "ai-model-benchmarking-ui-validation.csv";
const BENCHMARK_DATASET_CSV = [
  "text,sentiment",
  "\"This product is excellent fast useful and stable\",positive",
  "\"The support was poor broken slow and frustrating\",negative",
  "\"The connector interface is acceptable consistent predictable and standard\",neutral",
  "\"The benchmark dashboard feels useful helpful and innovative\",positive",
  "\"Refund delay support issue made the workflow poor\",negative",
].join("\n");

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 or run Level 6 with the INESData adapter to validate AI Model Benchmarking from the INESData UI.",
);

function modelServerUrl(componentsNamespace: string, path: string): string {
  return modelServerUrlForPath(path, componentsNamespace);
}

function aiModelHubCatalogCleanupEnabled(): boolean {
  return process.env.UI_AI_MODEL_HUB_CATALOG_CLEANUP === "1";
}

function aiModelMetadataAliases({
  task,
  subtask,
  algorithm,
  library,
  framework,
  software,
  inferencePath,
}: {
  task: string;
  subtask: string;
  algorithm: string;
  library: string;
  framework: string;
  software: string;
  inferencePath: string;
}): Record<string, unknown> {
  const inputFeatures = JSON.stringify(TEXT_MODEL_INPUT_FEATURES);
  const inputSchema = JSON.stringify(TEXT_MODEL_INPUT_SCHEMA);
  const inputExample = JSON.stringify(TEXT_MODEL_INPUT_EXAMPLE);

  const metadata = {
    "daimo:asset_kind": "model",
    "daimo:task": task,
    "https://w3id.org/daimo/ns#task": task,
    "https://pionera.ai/edc/daimo#task": task,
    "daimo:subtask": subtask,
    "https://w3id.org/daimo/ns#subtask": subtask,
    "https://pionera.ai/edc/daimo#subtask": subtask,
    "daimo:algorithm": algorithm,
    "https://w3id.org/daimo/ns#algorithm": algorithm,
    "https://pionera.ai/edc/daimo#algorithm": algorithm,
    "daimo:library": library,
    "https://w3id.org/daimo/ns#library": library,
    "https://pionera.ai/edc/daimo#library": library,
    "daimo:framework": framework,
    "https://w3id.org/daimo/ns#framework": framework,
    "https://pionera.ai/edc/daimo#framework": framework,
    "daimo:software": software,
    "https://w3id.org/daimo/ns#software": software,
    "https://pionera.ai/edc/daimo#software": software,
    "daimo:inference_path": inferencePath,
    "https://w3id.org/daimo/ns#inference_path": inferencePath,
    "https://pionera.ai/edc/daimo#inference_path": inferencePath,
    "daimo:input_features": inputFeatures,
    "https://w3id.org/daimo/ns#input_features": inputFeatures,
    "https://pionera.ai/edc/daimo#input_features": inputFeatures,
    "daimo:input_schema": inputSchema,
    "https://w3id.org/daimo/ns#input_schema": inputSchema,
    "https://pionera.ai/edc/daimo#input_schema": inputSchema,
    "daimo:input_example": inputExample,
    "https://w3id.org/daimo/ns#input_example": inputExample,
    "https://pionera.ai/edc/daimo#input_example": inputExample,
    task,
    subtask,
    algorithm,
    library,
    framework,
    software,
    inference_path: inferencePath,
    inferencePath,
    input_features: inputFeatures,
    inputFeatures: TEXT_MODEL_INPUT_FEATURES,
    input_schema: inputSchema,
    inputSchema: TEXT_MODEL_INPUT_SCHEMA,
    input_example: inputExample,
    inputExample: TEXT_MODEL_INPUT_EXAMPLE,
  };

  return metadata;
}

async function gotoAiModelBenchmarking(page: Page, baseUrl: string): Promise<void> {
  await page.goto(`${baseUrl.replace(/\/$/, "")}/ai-model-benchmarking`, {
    waitUntil: "domcontentloaded",
  });
}

function modelItem(page: Page, modelName: string) {
  return page.locator(".model-item.selectable").filter({ hasText: modelName }).first();
}

function selectedModelBadge(page: Page, modelName: string) {
  return modelItem(page, modelName).locator(".selected-badge").filter({ hasText: /SELECTED/i }).first();
}

function benchmarkSearchInput(page: Page) {
  return page.locator("input.search-input").first();
}

function validationDatasetCsvBuffer(): Buffer {
  return Buffer.from(BENCHMARK_DATASET_CSV, "utf8");
}

function extractBenchmarkRunIdFromUrl(url: string): string {
  const pathname = new URL(url).pathname.replace(/\/+$/, "");
  return decodeURIComponent(pathname.split("/").pop() || "");
}

async function inspectBenchmarkObserverEvidence(page: Page, benchmarkRunId: string) {
  const loadError = page.getByText(/Failed to load benchmark evidence/i).first();
  const emptyTimeline = page.getByText(/No benchmark events match/i).first();
  const startedEvent = page.getByRole("heading", { name: /^BENCHMARK_STARTED$/i }).first();
  const completedEvent = page.getByRole("heading", { name: /^BENCHMARK_COMPLETED$/i }).first();

  await expect(async () => {
    const hasLoadError = await loadError.isVisible().catch(() => false);
    const hasEmptyTimeline = await emptyTimeline.isVisible().catch(() => false);
    const hasStartedEvent = await startedEvent.isVisible().catch(() => false);
    const hasCompletedEvent = await completedEvent.isVisible().catch(() => false);
    expect(hasLoadError || hasEmptyTimeline || (hasStartedEvent && hasCompletedEvent)).toBeTruthy();
  }).toPass({
    timeout: 30_000,
    intervals: EVENTUAL_UI_RETRY_INTERVALS,
  });

  if (await loadError.isVisible().catch(() => false)) {
    return {
      status: "skipped" as const,
      reason: "Observer backend is not available from the connector UI in this environment.",
      observedEvents: [],
    };
  }

  if (await emptyTimeline.isVisible().catch(() => false)) {
    throw new Error(`Observer benchmark evidence is empty for benchmarkRunId ${benchmarkRunId}.`);
  }

  await expect(startedEvent).toBeVisible();
  await expect(completedEvent).toBeVisible();
  await expect(page.getByText(/Rows:\s*5/i).first()).toBeVisible();
  await expect(page.getByText(/Metrics:/i).first()).toBeVisible();
  await expect(page.getByText(/totalModels/i).first()).toBeVisible();
  await expect(page.getByText(/topModelName/i).first()).toBeVisible();

  return {
    status: "passed" as const,
    observedEvents: ["BENCHMARK_STARTED", "BENCHMARK_COMPLETED"],
  };
}

test("13 AI Model Benchmarking: compare two local model-server endpoints from INESData UI", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "This demo validates the INESData connector UI path.");

  const suffix = `amh-bench-${Date.now()}`;
  const models: BenchmarkModelFixture[] = [
    {
      assetId: `qa-ui-amh-bench-ecommerce-${suffix}`,
      name: `AI Model Benchmark Ecommerce Sentiment ${suffix}`,
      path: DEFAULT_ECOMMERCE_PATH,
      url: modelServerUrl(dataspaceRuntime.componentsNamespace, DEFAULT_ECOMMERCE_PATH),
      routeKey: "nlp.ecommerce-sentiment",
    },
    {
      assetId: `qa-ui-amh-bench-twitter-${suffix}`,
      name: `AI Model Benchmark Twitter Sentiment ${suffix}`,
      path: DEFAULT_TWITTER_PATH,
      url: modelServerUrl(dataspaceRuntime.componentsNamespace, DEFAULT_TWITTER_PATH),
      routeKey: "nlp.twitter-sentiment",
    },
  ];
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const report: AIModelBenchmarkingUiReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    suffix,
    models,
    validationDataset: {
      fileName: BENCHMARK_DATASET_FILE,
      rows: 5,
    },
    outputPreparationChecks: [],
    suggestedDatasetChecks: [],
    exportChecks: [],
    observerEvidenceChecks: [],
    linkedCases: ["PT5-MH-12", "PT5-MH-13", "PT5-MH-14", "PT5-MH-15", "MH-OBS-05", "DS-UI-AMH-BENCH-01"],
    providerBootstrap: [],
    errorResponses: [],
    toleratedErrorResponses: [],
    fatalErrorResponses: [],
  };

  const isTolerableRuntimeRetry = (url: string, status: number): boolean =>
    (status === 401 || status === 500 || status === 502 || status === 503 || status === 504) &&
    (url.includes("/management/pagination/count") ||
      url.includes("/management/assets/request") ||
      url.includes("/management/federatedcatalog/request") ||
      url.includes("/management/contractagreements/request"));

  page.on("response", (response) => {
    const url = response.url();
    if (
      response.status() >= 400 &&
      (url.includes("/management/") || url.includes("/modelexecutions/execute"))
    ) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    if (aiModelHubCatalogCleanupEnabled()) {
      await attachJson(
        "ai-model-benchmarking-ui-catalog-cleanup",
        await cleanupProviderValidationArtifacts(request, dataspaceRuntime, {
          contractdefinitions: ["contract-ui-", "qa-ui-contract-definition-"],
          policydefinitions: ["policy-ui-", "qa-ui-policy-", "qa-ui-contract-policy-"],
          assets: [
            "asset-e2e-",
            "qa-ui-asset-",
            "qa-ui-amh-bench-",
            "qa-ui-amh-browser-",
            "qa-ui-amh-exec-",
            "qa-ui-amh-httpdata-",
            "qa-ui-catalog-",
            "qa-ui-negotiation-",
            "qa-ui-sv-httpdata-",
            "qa-ui-transfer-",
          ],
        }),
      );
    }

    for (const model of models) {
      const providerBootstrap = await bootstrapProviderNegotiationArtifacts(
        request,
        dataspaceRuntime,
        model.assetId,
        `${suffix}-${model.routeKey.replace(/[^a-z0-9]+/gi, "-")}`,
        {
          sourceObjectName: `${model.assetId}.json`,
          name: model.name,
          version: "1.0.0",
          shortDescription: "Temporary deterministic model-server endpoint for AI Model Benchmarking validation",
          description:
            "Controlled model-server endpoint used to validate model comparison from the INESData connector interface before replacing the fixture with real A5.2 models.",
          assetType: "machineLearning",
          keywords: ["validation", "ai-model-benchmarking", "model-server", "sentiment", "machine-learning", "HttpData", "A5.2"],
          properties: {
            ...aiModelMetadataAliases({
              task: "classification",
              subtask: "sentiment-analysis",
              algorithm: "deterministic-rule-engine",
              library: "flask",
              framework: "model-server",
              software: "pionera-validation-framework",
              inferencePath: model.path,
            }),
            contenttype: "application/json",
            format: "json",
          },
          dataAddress: {
            type: "HttpData",
            baseUrl: model.url,
            method: "POST",
            name: `${model.assetId}.json`,
          },
        },
      );
      report.providerBootstrap.push(providerBootstrap);
    }
    await attachJson("ai-model-benchmarking-ui-bootstrap", report.providerBootstrap);

    await loginPage.open(dataspaceRuntime.provider.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-ai-model-benchmarking-after-login");

    await expect(async () => {
      await gotoAiModelBenchmarking(page, dataspaceRuntime.provider.portalBaseUrl);
      await shellPage.assertNoGateway403("AI Model Benchmarking page");
      await shellPage.assertNoServerErrorBanner("AI Model Benchmarking page");
      await expect(page.getByRole("heading", { name: /Model Benchmarking/i })).toBeVisible({ timeout: 20_000 });
      await expect(benchmarkSearchInput(page)).toBeVisible({ timeout: 20_000 });
      await benchmarkSearchInput(page).fill(suffix);
      await waitForUiTransition(page);
      await expect(modelItem(page, models[0].name)).toBeVisible({ timeout: 20_000 });
      await expect(modelItem(page, models[1].name)).toBeVisible({ timeout: 20_000 });
    }).toPass({
      timeout: 120_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    await clickMarked(modelItem(page, models[0].name), { force: true });
    await expect(selectedModelBadge(page, models[0].name)).toBeVisible({ timeout: 10_000 });
    await expect(modelItem(page, models[1].name)).toBeVisible({ timeout: 10_000 });
    await clickMarked(modelItem(page, models[1].name), { force: true });
    await expect(selectedModelBadge(page, models[1].name)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/2 selected/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/classification/i).first()).toBeVisible({ timeout: 10_000 });
    await captureStep(page, "02-ai-model-benchmarking-models-selected");

    await clickMarked(page.getByRole("button", { name: /Validate Input/i }).first(), { force: true });
    await expect(page.getByText(/Input validation passed/i).first()).toBeVisible({ timeout: 10_000 });
    report.outputPreparationChecks.push({
      scenario: "validate_generated_single_input",
      expectedMessage: "Input validation passed. You can now obtain outputs.",
      status: "passed",
    });

    await expect(page.getByRole("button", { name: /Obtain Outputs/i }).first()).toBeEnabled({ timeout: 10_000 });
    await clickMarked(page.getByRole("button", { name: /Obtain Outputs/i }).first(), { force: true });
    await expect(page.getByText(/Outputs ready\. Success:\s*2,\s*Partial:\s*0,\s*Errors:\s*0/i).first()).toBeVisible({
      timeout: 90_000,
    });
    const outputsPanel = page.locator(".outputs-panel").first();
    await expect(outputsPanel.getByText(models[0].name).first()).toBeVisible({ timeout: 10_000 });
    await expect(outputsPanel.getByText(models[1].name).first()).toBeVisible({ timeout: 10_000 });
    await expect(outputsPanel.locator(".output-state.success")).toHaveCount(2, { timeout: 10_000 });
    report.outputPreparationChecks.push({
      scenario: "obtain_outputs_for_selected_models",
      expectedMessage: "Outputs ready. Success: 2, Partial: 0, Errors: 0.",
      status: "passed",
    });
    await attachJson("ai-model-benchmarking-ui-output-preparation", {
      selectedModels: models.map((model) => ({ assetId: model.assetId, name: model.name, path: model.path })),
      inputExample: TEXT_MODEL_INPUT_EXAMPLE,
      checks: report.outputPreparationChecks,
    });
    await captureStep(page, "03-ai-model-benchmarking-outputs-ready");

    const suggestedDatasetCard = page.locator(".suggested-dataset-card").filter({ hasText: /Starter CSV/i }).first();
    await expect(suggestedDatasetCard).toBeVisible({ timeout: 10_000 });
    const [suggestedDatasetDownload] = await Promise.all([
      page.waitForEvent("download"),
      clickMarked(suggestedDatasetCard.getByRole("button", { name: /CSV/i }).first(), { force: true }),
    ]);
    const suggestedDatasetFileName = suggestedDatasetDownload.suggestedFilename();
    expect(suggestedDatasetFileName).toMatch(/-benchmark-sample-starter\.csv$/);
    const suggestedDatasetPath = await suggestedDatasetDownload.path();
    if (!suggestedDatasetPath) {
      throw new Error(`Suggested dataset download did not produce a readable path: ${suggestedDatasetFileName}`);
    }
    const suggestedDatasetCsv = await readFile(suggestedDatasetPath, "utf8");
    const requiredSuggestedDatasetContent = ["text", "sentiment", "Sample 1", "label"];
    for (const requiredContent of requiredSuggestedDatasetContent) {
      expect(suggestedDatasetCsv).toContain(requiredContent);
    }
    report.suggestedDatasetChecks.push({
      scenario: "download_suggested_starter_dataset",
      fileName: suggestedDatasetFileName,
      requiredContent: requiredSuggestedDatasetContent,
      status: "passed",
    });
    await attachJson("ai-model-benchmarking-ui-suggested-dataset", {
      fileName: suggestedDatasetFileName,
      preview: suggestedDatasetCsv.split(/\r?\n/).slice(0, 6),
      checks: report.suggestedDatasetChecks,
    });

    await setInputFilesMarked(page.locator("#validation-dataset-file"), {
      name: BENCHMARK_DATASET_FILE,
      mimeType: "text/csv",
      buffer: validationDatasetCsvBuffer(),
    });
    await expect(page.getByText(new RegExp(`Dataset loaded: ${BENCHMARK_DATASET_FILE}`, "i")).first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText(/Rows validated:\s*5/i).first()).toBeVisible({ timeout: 10_000 });
    await captureStep(page, "04-ai-model-benchmarking-dataset-loaded");

    await expect(page.getByRole("button", { name: /^Run Benchmark$/i }).first()).toBeEnabled({ timeout: 10_000 });
    await clickMarked(page.getByRole("button", { name: /^Run Benchmark$/i }).first(), { force: true });
    await expect(page.getByText(/Benchmark completed/i).first()).toBeVisible({ timeout: 90_000 });
    await expect(page.getByRole("heading", { name: /Ranking Results/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/2 models evaluated/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(models[0].name).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(models[1].name).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Best Model by/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Benchmark Evidence/i).first()).toBeVisible({ timeout: 10_000 });

    const [exportDownload] = await Promise.all([
      page.waitForEvent("download"),
      clickMarked(page.getByRole("button", { name: /Export CSV/i }).first(), { force: true }),
    ]);
    const exportFileName = exportDownload.suggestedFilename();
    expect(exportFileName).toMatch(/^model-benchmark-results-\d+\.csv$/);
    const exportPath = await exportDownload.path();
    if (!exportPath) {
      throw new Error(`CSV export did not produce a readable download path: ${exportFileName}`);
    }
    const exportCsv = await readFile(exportPath, "utf8");
    const requiredExportContent = [
      "Rank,Model Name,Model ID",
      models[0].name,
      models[1].name,
      "Models Compared,2",
    ];
    for (const requiredContent of requiredExportContent) {
      expect(exportCsv).toContain(requiredContent);
    }
    report.exportChecks.push({
      scenario: "export_ranking_csv",
      fileName: exportFileName,
      requiredContent: requiredExportContent,
      status: "passed",
    });
    await attachJson("ai-model-benchmarking-ui-csv-export", {
      fileName: exportFileName,
      preview: exportCsv.split(/\r?\n/).slice(0, 8),
      checks: report.exportChecks,
    });
    await captureStep(page, "05-ai-model-benchmarking-ranking-results");

    await clickMarked(page.getByRole("button", { name: /Benchmark Evidence/i }).first(), { force: true });
    await expect(page).toHaveURL(/\/ai-model-observer\/benchmarks\/benchmark-/i, { timeout: 10_000 });
    const benchmarkRunId = extractBenchmarkRunIdFromUrl(page.url());
    expect(benchmarkRunId).toMatch(/^benchmark-/);
    const observerEvidenceOutcome = await inspectBenchmarkObserverEvidence(page, benchmarkRunId);
    report.observerEvidenceChecks.push({
      scenario: "open_benchmark_observer_evidence",
      benchmarkRunId,
      url: page.url(),
      observedEvents: observerEvidenceOutcome.observedEvents,
      status: observerEvidenceOutcome.status,
      reason: observerEvidenceOutcome.reason,
    });
    await attachJson("ai-model-benchmarking-ui-observer-evidence", {
      benchmarkRunId,
      url: page.url(),
      checks: report.observerEvidenceChecks,
    });
    await captureStep(page, "06-ai-model-benchmarking-observer-evidence");

    await attachJson("ai-model-benchmarking-ui-result-assertions", {
      selectedModels: models.map((model) => ({ assetId: model.assetId, name: model.name, path: model.path })),
      validationDataset: report.validationDataset,
      outputPreparationChecks: report.outputPreparationChecks,
      suggestedDatasetChecks: report.suggestedDatasetChecks,
      exportChecks: report.exportChecks,
      observerEvidenceChecks: report.observerEvidenceChecks,
      expectedRankingRows: 2,
      expectedMetrics: ["AUC", "GINI", "Precision", "Recall", "F1 Score"],
    });

    report.toleratedErrorResponses = report.errorResponses.filter(({ url, status }) =>
      isTolerableRuntimeRetry(url, status),
    );
    report.fatalErrorResponses = report.errorResponses.filter(
      ({ url, status }) => !isTolerableRuntimeRetry(url, status),
    );
    expect(
      report.fatalErrorResponses,
      `API calls returned fatal errors: ${JSON.stringify(report.fatalErrorResponses)} (tolerated transient runtime errors: ${JSON.stringify(report.toleratedErrorResponses)})`,
    ).toHaveLength(0);
  } finally {
    const browserDiagnosticsSnapshot = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("ai-model-benchmarking-ui-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("ai-model-benchmarking-ui-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
