import { readFile } from "fs/promises";
import { Page } from "@playwright/test";

import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import { clickMarked, fillMarked, setInputFilesMarked } from "../../../shared/utils/live-marker";
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

const DEFAULT_BENCHMARK_MODEL_PATHS = [
  "/flares/dccuchile-distilbert-base-spanish-uncased-reliability",
  "/flares/dccuchile-bert-base-spanish-wwm-uncased-reliability",
];
const FLARES_INPUT_COLUMNS = ["Id", "Text", "5W1H_Label", "Tag_Text", "Tag_Start", "Tag_End"];
const FLARES_MODEL_INPUT_FEATURES = [
  {
    name: "Id",
    type: "integer",
    required: true,
    description: "FLARES record identifier",
  },
  {
    name: "Text",
    type: "string",
    required: true,
    description: "News text to classify",
  },
  {
    name: "5W1H_Label",
    type: "string",
    required: true,
    description: "5W1H class associated with the tagged span",
  },
  {
    name: "Tag_Text",
    type: "string",
    required: true,
    description: "Tagged evidence span",
  },
  {
    name: "Tag_Start",
    type: "integer",
    required: true,
    description: "Tagged span start offset",
  },
  {
    name: "Tag_End",
    type: "integer",
    required: true,
    description: "Tagged span end offset",
  },
];
const FLARES_MODEL_INPUT_SCHEMA = {
  type: "array",
  items: {
    type: "object",
    required: FLARES_INPUT_COLUMNS,
    properties: {
      Id: { type: "integer" },
      Text: { type: "string" },
      "5W1H_Label": { type: "string" },
      Tag_Text: { type: "string" },
      Tag_Start: { type: "integer" },
      Tag_End: { type: "integer" },
    },
  },
};
const FLARES_MODEL_INPUT_EXAMPLE = [
  {
    Id: 523,
    Text: "Estos diagnosticos elevan a 11 el total de casos confirmados de la cepa britanica en Espana, dado que a los seis de Madrid se anaden los cinco reportados hasta el momento por Andalucia.",
    "5W1H_Label": "WHEN",
    Tag_Text: "hasta el momento",
    Tag_Start: 154,
    Tag_End: 170,
  },
];
const BENCHMARK_DATASET_FILE = "ai-model-benchmarking-ui-flares-validation.json";
const BENCHMARK_DATASET_ROWS = [
  {
    Id: 523,
    Text: "Estos diagnosticos elevan a 11 el total de casos confirmados de la cepa britanica en Espana, dado que a los seis de Madrid se anaden los cinco reportados hasta el momento por Andalucia.",
    "5W1H_Label": "WHEN",
    Tag_Text: "hasta el momento",
    Tag_Start: 154,
    Tag_End: 170,
    expected_label: "semiconfiable",
  },
  {
    Id: 524,
    Text: "La organizacion confirmo que el informe se publicara manana tras completar la revision tecnica.",
    "5W1H_Label": "WHEN",
    Tag_Text: "manana",
    Tag_Start: 44,
    Tag_End: 50,
    expected_label: "confiable",
  },
  {
    Id: 525,
    Text: "Fuentes municipales indicaron que las obras empezaran en el barrio norte durante el verano.",
    "5W1H_Label": "WHERE",
    Tag_Text: "barrio norte",
    Tag_Start: 63,
    Tag_End: 75,
    expected_label: "confiable",
  },
  {
    Id: 526,
    Text: "El comunicado atribuye la decision a un comite independiente sin publicar el acta completa.",
    "5W1H_Label": "WHO",
    Tag_Text: "comite independiente",
    Tag_Start: 40,
    Tag_End: 60,
    expected_label: "semiconfiable",
  },
  {
    Id: 527,
    Text: "La nota viral asegura que todos los servicios quedaran cancelados, aunque no cita ninguna fuente oficial.",
    "5W1H_Label": "WHAT",
    Tag_Text: "todos los servicios quedaran cancelados",
    Tag_Start: 26,
    Tag_End: 65,
    expected_label: "no confiable",
  },
];

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 or run Level 6 with the INESData adapter to validate AI Model Benchmarking from the INESData UI.",
);
test.skip(
  process.env.UI_AI_MODEL_HUB_BENCHMARKING_DEMO === "0",
  "AI Model Benchmarking UI validation is disabled for the configured model-server contract.",
);

function modelServerUrl(componentsNamespace: string, path: string): string {
  return modelServerUrlForPath(path, componentsNamespace);
}

function normalizePath(value: string): string {
  const trimmed = value.trim();
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function configuredBenchmarkModelPaths(): string[] {
  const raw = (process.env.UI_AI_MODEL_HUB_BENCHMARK_MODEL_PATHS || "").trim();
  const values = raw
    ? raw.replace(/;/g, ",").split(",").map((entry) => entry.trim()).filter((entry) => entry.length > 0)
    : DEFAULT_BENCHMARK_MODEL_PATHS;
  return values.slice(0, 2).map(normalizePath);
}

function labelForModelPath(path: string): string {
  const lowerPath = path.toLowerCase();
  if (lowerPath.includes("distilbert")) return "DistilBERT";
  if (lowerPath.includes("albert")) return "ALBERT";
  if (lowerPath.includes("bert")) return "BERT";
  return path.split("/").filter(Boolean).pop() || "HTTP";
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
  const inputFeatures = JSON.stringify(FLARES_MODEL_INPUT_FEATURES);
  const inputSchema = JSON.stringify(FLARES_MODEL_INPUT_SCHEMA);
  const inputExample = JSON.stringify(FLARES_MODEL_INPUT_EXAMPLE);
  const inputColumns = JSON.stringify(FLARES_INPUT_COLUMNS);
  const targetFields = JSON.stringify(["expected_label"]);
  const predictionFields = JSON.stringify(["Reliability_Label"]);

  const metadata = {
    "daimo:asset_kind": "model",
    "daimo:taskCategory": "Natural Language Processing",
    "https://w3id.org/pionera/daimo#taskCategory": "Natural Language Processing",
    taskCategory: "Natural Language Processing",
    "daimo:taskType": task,
    "https://w3id.org/pionera/daimo#taskType": task,
    taskType: task,
    "daimo:task": task,
    "https://w3id.org/daimo/ns#task": task,
    "https://pionera.ai/edc/daimo#task": task,
    "daimo:subtask": subtask,
    "https://w3id.org/pionera/daimo#subtask": subtask,
    "https://w3id.org/daimo/ns#subtask": subtask,
    "https://pionera.ai/edc/daimo#subtask": subtask,
    "daimo:algorithm": algorithm,
    "https://w3id.org/daimo/ns#algorithm": algorithm,
    "https://pionera.ai/edc/daimo#algorithm": algorithm,
    "daimo:libraryName": library,
    "https://w3id.org/pionera/daimo#libraryName": library,
    libraryName: library,
    "daimo:library": library,
    "https://w3id.org/daimo/ns#library": library,
    "https://pionera.ai/edc/daimo#library": library,
    "daimo:framework": framework,
    "https://w3id.org/daimo/ns#framework": framework,
    "https://pionera.ai/edc/daimo#framework": framework,
    "daimo:software": software,
    "https://w3id.org/daimo/ns#software": software,
    "https://pionera.ai/edc/daimo#software": software,
    "daimo:modality": "text",
    "https://w3id.org/pionera/daimo#modality": "text",
    modality: "text",
    "daimo:endpointBehavior": "prediction",
    "https://w3id.org/pionera/daimo#endpointBehavior": "prediction",
    endpointBehavior: "prediction",
    "daimo:inference_path": inferencePath,
    "https://w3id.org/daimo/ns#inference_path": inferencePath,
    "https://pionera.ai/edc/daimo#inference_path": inferencePath,
    "daimo:inputSchema": inputSchema,
    "https://w3id.org/pionera/daimo#inputSchema": inputSchema,
    "daimo:input_features": inputFeatures,
    "https://w3id.org/daimo/ns#input_features": inputFeatures,
    "https://pionera.ai/edc/daimo#input_features": inputFeatures,
    "daimo:input_schema": inputSchema,
    "https://w3id.org/daimo/ns#input_schema": inputSchema,
    "https://pionera.ai/edc/daimo#input_schema": inputSchema,
    "daimo:inputExample": inputExample,
    "https://w3id.org/pionera/daimo#inputExample": inputExample,
    "daimo:input_example": inputExample,
    "https://w3id.org/daimo/ns#input_example": inputExample,
    "https://pionera.ai/edc/daimo#input_example": inputExample,
    "daimo:input": inputColumns,
    "https://w3id.org/pionera/daimo#input": inputColumns,
    input: inputColumns,
    "daimo:input_columns": inputColumns,
    "https://w3id.org/daimo/ns#input_columns": inputColumns,
    "https://pionera.ai/edc/daimo#input_columns": inputColumns,
    "daimo:target_field": "expected_label",
    "https://w3id.org/daimo/ns#target_field": "expected_label",
    "https://pionera.ai/edc/daimo#target_field": "expected_label",
    "daimo:target_fields": targetFields,
    "daimo:prediction_field": "Reliability_Label",
    "https://w3id.org/daimo/ns#prediction_field": "Reliability_Label",
    "https://pionera.ai/edc/daimo#prediction_field": "Reliability_Label",
    "daimo:predictionField": "Reliability_Label",
    "https://w3id.org/pionera/daimo#predictionField": "Reliability_Label",
    predictionField: "Reliability_Label",
    "daimo:prediction_fields": predictionFields,
    "daimo:predictionFields": predictionFields,
    "https://w3id.org/pionera/daimo#predictionFields": predictionFields,
    "daimo:requestShape": "batch",
    "https://w3id.org/pionera/daimo#requestShape": "batch",
    "daimo:request_shape": "batch",
    "https://w3id.org/daimo/ns#request_shape": "batch",
    "https://pionera.ai/edc/daimo#request_shape": "batch",
    "daimo:metrics": JSON.stringify(["Accuracy", "Precision", "Recall", "F1 Score"]),
    "https://w3id.org/pionera/daimo#metrics": JSON.stringify(["Accuracy", "Precision", "Recall", "F1 Score"]),
    task,
    taskCategory: "Natural Language Processing",
    taskType: task,
    subtask,
    algorithm,
    library,
    libraryName: library,
    framework,
    software,
    modality: "text",
    endpointBehavior: "prediction",
    inference_path: inferencePath,
    inferencePath,
    input_columns: inputColumns,
    input: inputColumns,
    inputColumns: FLARES_INPUT_COLUMNS,
    target_field: "expected_label",
    targetFields: ["expected_label"],
    prediction_field: "Reliability_Label",
    predictionFields: ["Reliability_Label"],
    request_shape: "batch",
    requestShape: "batch",
    metrics: ["Accuracy", "Precision", "Recall", "F1 Score"],
    input_features: inputFeatures,
    inputFeatures: FLARES_MODEL_INPUT_FEATURES,
    input_schema: inputSchema,
    inputSchema: FLARES_MODEL_INPUT_SCHEMA,
    input_example: inputExample,
    inputExample: FLARES_MODEL_INPUT_EXAMPLE,
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
  return modelItem(page, modelName).locator(".model-status").filter({ hasText: /Selected/i }).first();
}

function benchmarkSearchInput(page: Page) {
  return page.locator("input.search-input").first();
}

function validationDatasetJsonBuffer(): Buffer {
  return Buffer.from(JSON.stringify(BENCHMARK_DATASET_ROWS, null, 2), "utf8");
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
  const modelExecutionCompletedEvent = page.getByRole("heading", { name: /^MODEL_EXECUTION_COMPLETED$/i }).first();

  await expect(async () => {
    const hasLoadError = await loadError.isVisible().catch(() => false);
    const hasEmptyTimeline = await emptyTimeline.isVisible().catch(() => false);
    const hasStartedEvent = await startedEvent.isVisible().catch(() => false);
    const hasCompletedEvent = await completedEvent.isVisible().catch(() => false);
    const hasModelExecutionCompletedEvent = await modelExecutionCompletedEvent.isVisible().catch(() => false);
    expect(hasLoadError || hasEmptyTimeline || (hasStartedEvent && hasCompletedEvent && hasModelExecutionCompletedEvent)).toBeTruthy();
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
  await expect(modelExecutionCompletedEvent).toBeVisible();
  await expect(page.getByText(/HTTP:\s*200/i).first()).toBeVisible();
  await expect(page.getByText(/Participant:\s*conn-org2-pionera/i).first()).toBeVisible();

  return {
    status: "passed" as const,
    observedEvents: ["BENCHMARK_STARTED", "BENCHMARK_COMPLETED", "MODEL_EXECUTION_COMPLETED"],
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
  const models: BenchmarkModelFixture[] = configuredBenchmarkModelPaths().map((path, index) => ({
    assetId: `qa-ui-amh-bench-flares-${index + 1}-${suffix}`,
    name: `AI Model Benchmark FLARES Reliability ${labelForModelPath(path)} ${suffix}`,
    path,
    url: modelServerUrl(dataspaceRuntime.componentsNamespace, path),
    routeKey: `flares.${labelForModelPath(path).toLowerCase()}`,
  }));
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
          shortDescription: "AIModelHub-Use-Cases FLARES endpoint for AI Model Benchmarking validation",
          description:
            "AIModelHub-Use-Cases FLARES reliability model-server endpoint used to validate model comparison from the INESData connector interface.",
          assetType: "machineLearning",
          keywords: ["validation", "ai-model-benchmarking", "model-server", "flares", "reliability", "machine-learning", "HttpData", "A5.2"],
          properties: {
            ...aiModelMetadataAliases({
              task: "classification",
              subtask: "flares-reliability",
              algorithm: labelForModelPath(model.path),
              library: "transformers",
              framework: "flares",
              software: "AIModelHub-Use-Cases",
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

    await fillMarked(page.locator(".dataset-mapping-textarea").first(), FLARES_INPUT_COLUMNS.join(", "));
    await fillMarked(page.locator(".dataset-mapping-input").first(), "expected_label");
    report.outputPreparationChecks.push({
      scenario: "configure_flares_dataset_mapping",
      expectedMessage: "Input columns and label column configured for real FLARES batch payloads.",
      status: "passed",
    });

    await attachJson("ai-model-benchmarking-ui-output-preparation", {
      selectedModels: models.map((model) => ({ assetId: model.assetId, name: model.name, path: model.path })),
      inputColumns: FLARES_INPUT_COLUMNS,
      labelColumn: "expected_label",
      inputExample: FLARES_MODEL_INPUT_EXAMPLE,
      checks: report.outputPreparationChecks,
    });
    await captureStep(page, "03-ai-model-benchmarking-mapping-ready");

    await setInputFilesMarked(page.locator("#validation-dataset-file"), {
      name: BENCHMARK_DATASET_FILE,
      mimeType: "application/json",
      buffer: validationDatasetJsonBuffer(),
    });
    await expect(page.getByText(new RegExp(`Dataset loaded: ${BENCHMARK_DATASET_FILE}`, "i")).first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText(/Rows(?: validated)?:\s*5/i).first()).toBeVisible({ timeout: 10_000 });
    await captureStep(page, "04-ai-model-benchmarking-dataset-loaded");

    await expect(page.getByRole("button", { name: /^Test Rows$/i }).first()).toBeEnabled({ timeout: 10_000 });
    await clickMarked(page.getByRole("button", { name: /^Test Rows$/i }).first(), { force: true });
    await expect(page.getByText(/Row test complete/i).first()).toBeVisible({ timeout: 90_000 });
    await captureStep(page, "05-ai-model-benchmarking-row-test-complete");

    const runBenchmarkButton = page.getByRole("button", { name: /^Run Benchmark$/i }).first();
    await expect(runBenchmarkButton).toBeEnabled({ timeout: 10_000 });
    await runBenchmarkButton.scrollIntoViewIfNeeded();
    await runBenchmarkButton.evaluate((button) => (button as HTMLButtonElement).click());
    await expect(page.getByText(/Benchmark completed/i).first()).toBeVisible({ timeout: 90_000 });
    await expect(page.getByRole("heading", { name: /Ranking Results/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/2 models evaluated/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(models[0].name).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(models[1].name).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Top candidate|Best composite score/i).first()).toBeVisible({ timeout: 10_000 });
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
    await captureStep(page, "06-ai-model-benchmarking-ranking-results");

    const benchmarkEvidenceButton = page.getByRole("button", { name: /Benchmark Evidence/i }).first();
    await expect(benchmarkEvidenceButton).toBeEnabled({ timeout: 10_000 });
    await benchmarkEvidenceButton.evaluate((button) => (button as HTMLButtonElement).click());
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
    await captureStep(page, "07-ai-model-benchmarking-observer-evidence");

    await attachJson("ai-model-benchmarking-ui-result-assertions", {
      selectedModels: models.map((model) => ({ assetId: model.assetId, name: model.name, path: model.path })),
      validationDataset: report.validationDataset,
      outputPreparationChecks: report.outputPreparationChecks,
      suggestedDatasetChecks: report.suggestedDatasetChecks,
      exportChecks: report.exportChecks,
      observerEvidenceChecks: report.observerEvidenceChecks,
      expectedRankingRows: 2,
      expectedMetrics: ["Accuracy", "Precision", "Recall", "F1 Score"],
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
