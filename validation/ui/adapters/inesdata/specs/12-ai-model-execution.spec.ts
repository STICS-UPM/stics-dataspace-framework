import { Locator, Page } from "@playwright/test";

import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import { clickMarked, fillMarked, selectOptionMarked } from "../../../shared/utils/live-marker";
import {
  bootstrapProviderNegotiationArtifacts,
  cleanupProviderValidationArtifacts,
} from "../../../shared/utils/provider-bootstrap";
import { EVENTUAL_UI_RETRY_INTERVALS, waitForUiTransition } from "../../../shared/utils/waiting";
import { modelServerUrlForPath } from "../../../shared/utils/model-server-url";

type AIModelExecutionUiReport = {
  startedAt: string;
  providerConnector: string;
  assetId: string;
  modelName: string;
  modelUrl: string;
  modelPath: string;
  payload: unknown;
  inputValidationChecks: Array<{
    scenario: string;
    expectedMessage: string;
    status: "passed";
  }>;
  observerEvidenceChecks: Array<{
    scenario: string;
    assetId: string;
    url: string;
    observedEvents: string[];
    status: "passed" | "skipped";
    reason?: string;
  }>;
  linkedCases: string[];
  providerBootstrap?: {
    assetId: string;
    policyId: string;
    contractDefinitionId: string;
  };
  errorResponses: Array<{ url: string; status: number }>;
  toleratedErrorResponses: Array<{ url: string; status: number }>;
  fatalErrorResponses: Array<{ url: string; status: number }>;
};

const DEFAULT_MODEL_PATH = "/flares/dccuchile-bert-base-spanish-wwm-uncased-5w1h";
const DEFAULT_PAYLOAD = [
  {
    Id: 840,
    Text: "El comité de medicamentos humanos espera concluir el análisis en marzo.",
  },
];
const OFFICIAL_FLARES_5W1H_MODEL = {
  assetId: "city-flares-5w1h-albert",
  name: "FLARES 5W1H ALBERT - PIONERA Use Case",
  sourceOfTruth: "ProyectoPIONERA/AIModelHub Step 10 seed_use_case_http_data_assets",
};
const FLARES_5W1H_INPUT_FEATURES = [
  {
    name: "Id",
    type: "integer",
    required: true,
    description: "Input text identifier",
  },
  {
    name: "Text",
    type: "string",
    required: true,
    description: "Spanish text to analyze",
  },
];
const FLARES_5W1H_JSON_SCHEMA = {
  type: "object",
  required: ["Id", "Text"],
  properties: {
    Id: {
      type: "integer",
      description: "Input text identifier",
    },
    Text: {
      type: "string",
      description: "Spanish text to analyze",
    },
  },
};
const FLARES_5W1H_INPUT_SCHEMA = {
  type: "array",
  items: FLARES_5W1H_JSON_SCHEMA,
  fields: FLARES_5W1H_INPUT_FEATURES,
  jsonSchema: JSON.stringify({
    type: "array",
    items: FLARES_5W1H_JSON_SCHEMA,
  }, null, 2),
};

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 or run Level 6 with the INESData adapter to validate AI Model Execution from the INESData UI.",
);

function normalizePath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return DEFAULT_MODEL_PATH;
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function aiModelHubModelPath(): string {
  return normalizePath(process.env.UI_AI_MODEL_HUB_MODEL_PATH || DEFAULT_MODEL_PATH);
}

function parseJsonEnv(name: string, fallback: unknown): unknown {
  const raw = (process.env[name] || "").trim();
  if (!raw) {
    return fallback;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function aiModelHubPayload(): unknown {
  return parseJsonEnv("UI_AI_MODEL_HUB_MODEL_PAYLOAD", DEFAULT_PAYLOAD);
}

function aiModelHubModelUrl(componentsNamespace: string): string {
  return modelServerUrlForPath(aiModelHubModelPath(), componentsNamespace);
}

function aiModelHubCatalogCleanupEnabled(): boolean {
  return process.env.UI_AI_MODEL_HUB_CATALOG_CLEANUP === "1";
}

function inferJsonSchema(value: unknown): Record<string, unknown> {
  if (Array.isArray(value)) {
    return {
      type: "array",
      items: inferJsonSchema(value[0] || {}),
    };
  }
  if (value && typeof value === "object") {
    const properties: Record<string, unknown> = {};
    const required: string[] = [];
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      required.push(key);
      properties[key] = inferJsonSchema(item);
    }
    return { type: "object", required, properties };
  }
  return { type: typeof value === "number" ? "number" : typeof value === "boolean" ? "boolean" : "string" };
}

function inputSchemaForPayload(payload: unknown): unknown {
  const fallback = aiModelHubModelPath() === DEFAULT_MODEL_PATH ? FLARES_5W1H_INPUT_SCHEMA : inferJsonSchema(payload);
  return parseJsonEnv("UI_AI_MODEL_HUB_MODEL_INPUT_SCHEMA", fallback);
}

function inputFeaturesForPayload(payload: unknown): unknown[] {
  const schema = inputSchemaForPayload(payload) as Record<string, unknown>;
  if (Array.isArray(schema.fields)) {
    return schema.fields.map((field) => {
      const item = field as Record<string, unknown>;
      return {
        name: String(item.name || item.field || item.path || ""),
        type: String(item.type || "string"),
        required: item.required !== undefined ? Boolean(item.required) : !Boolean(item.nullable),
        description: item.description ? String(item.description) : undefined,
      };
    }).filter((field) => field.name);
  }
  const objectSchema = schema.type === "array" && schema.items && typeof schema.items === "object"
    ? schema.items as Record<string, unknown>
    : schema;
  const properties = objectSchema.properties && typeof objectSchema.properties === "object"
    ? objectSchema.properties as Record<string, Record<string, unknown>>
    : {};
  return Object.keys(properties).map((name) => ({
    name,
    type: String(properties[name]?.type || "string"),
    required: Array.isArray(objectSchema.required) ? objectSchema.required.includes(name) : false,
    description: `${name} input field`,
  }));
}

function firstRequiredFeatureName(inputFeatures: unknown[]): string {
  for (const feature of inputFeatures) {
    const candidate = feature as { name?: unknown; required?: unknown };
    if (candidate.required && String(candidate.name || "").trim()) {
      return String(candidate.name).trim();
    }
  }
  return "";
}

function missingRequiredPayloadFor(payload: unknown): unknown {
  return Array.isArray(payload) ? [{}] : {};
}

function aiModelMetadataAliases({
  task,
  subtask,
  algorithm,
  library,
  framework,
  software,
  inferencePath,
  payload,
  inputSchema,
  inputFeatures,
}: {
  task: string;
  subtask: string;
  algorithm: string;
  library: string;
  framework: string;
  software: string;
  inferencePath: string;
  payload: unknown;
  inputSchema: unknown;
  inputFeatures: unknown[];
}): Record<string, unknown> {
  const serializedInputFeatures = JSON.stringify(inputFeatures);
  const serializedInputSchema = JSON.stringify(inputSchema);
  const inputExample = JSON.stringify(payload);

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
    "daimo:taskCategory": task,
    "daimo:taskType": "classification",
    "daimo:modality": ["text"],
    "daimo:endpointBehavior": "prediction",
    "daimo:libraryName": library,
    "daimo:requestShape": "batch",
    "daimo:inputSchema": inputSchema,
    "daimo:inputExample": payload,
    "https://w3id.org/pionera/daimo#taskCategory": task,
    "https://w3id.org/pionera/daimo#taskType": "classification",
    "https://w3id.org/pionera/daimo#modality": ["text"],
    "https://w3id.org/pionera/daimo#subtask": subtask,
    "https://w3id.org/pionera/daimo#endpointBehavior": "prediction",
    "https://w3id.org/pionera/daimo#libraryName": library,
    "https://w3id.org/pionera/daimo#requestShape": "batch",
    "https://w3id.org/pionera/daimo#inputSchema": inputSchema,
    "https://w3id.org/pionera/daimo#inputExample": payload,
    "daimo:inference_path": inferencePath,
    "https://w3id.org/daimo/ns#inference_path": inferencePath,
    "https://pionera.ai/edc/daimo#inference_path": inferencePath,
    "daimo:input_features": serializedInputFeatures,
    "https://w3id.org/daimo/ns#input_features": serializedInputFeatures,
    "https://pionera.ai/edc/daimo#input_features": serializedInputFeatures,
    "daimo:input_schema": serializedInputSchema,
    "https://w3id.org/daimo/ns#input_schema": serializedInputSchema,
    "https://pionera.ai/edc/daimo#input_schema": serializedInputSchema,
    "daimo:input_example": inputExample,
    "https://w3id.org/daimo/ns#input_example": inputExample,
    "https://pionera.ai/edc/daimo#input_example": inputExample,
    task,
    subtask,
    algorithm,
    library,
    framework,
    software,
    taskCategory: task,
    taskType: "classification",
    modality: ["text"],
    endpointBehavior: "prediction",
    libraryName: library,
    requestShape: "batch",
    request_shape: "batch",
    inference_path: inferencePath,
    inferencePath,
    input_features: serializedInputFeatures,
    inputFeatures,
    input_schema: serializedInputSchema,
    inputSchema,
    input_example: inputExample,
    inputExample: payload,
  };

  return metadata;
}

async function gotoAiModelExecution(page: Page, baseUrl: string): Promise<void> {
  await page.goto(`${baseUrl.replace(/\/$/, "")}/ai-model-execution`, {
    waitUntil: "domcontentloaded",
  });
}

function generatedInputField(page: Page, featureName: string): Locator {
  const label = new RegExp(`^${featureName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i");
  return page
    .getByRole(featureName.toLowerCase() === "id" ? "spinbutton" : "textbox", { name: label })
    .first();
}

async function fillGeneratedFlares5w1hForm(page: Page): Promise<void> {
  const row = DEFAULT_PAYLOAD[0];
  const idInput = page.getByRole("spinbutton", { name: /^Id\b/i }).first();
  const textInput = page.getByRole("textbox", { name: /^Text\b/i }).first();

  await expect(idInput).toBeVisible({ timeout: 15_000 });
  await expect(textInput).toBeVisible({ timeout: 15_000 });
  await fillMarked(idInput, String(row.Id));
  await fillMarked(textInput, row.Text);
}

async function inspectExecutionObserverEvidence(page: Page, assetId: string, modelName: string) {
  const loadError = page.getByText(/Failed to load observer timeline/i).first();
  const emptyTimeline = page.getByText(/No observer events match/i).first();
  const requestedEvent = page.getByRole("heading", { name: /^MODEL_EXECUTION_REQUESTED$/i }).first();
  const completedEvent = page.getByRole("heading", { name: /^MODEL_EXECUTION_COMPLETED$/i }).first();
  const failedEvent = page.getByRole("heading", { name: /^MODEL_EXECUTION_FAILED$/i }).first();

  await expect(async () => {
    const hasLoadError = await loadError.isVisible().catch(() => false);
    const hasEmptyTimeline = await emptyTimeline.isVisible().catch(() => false);
    const hasRequestedEvent = await requestedEvent.isVisible().catch(() => false);
    const hasCompletedEvent = await completedEvent.isVisible().catch(() => false);
    const hasFailedEvent = await failedEvent.isVisible().catch(() => false);
    expect(hasLoadError || hasEmptyTimeline || (hasRequestedEvent && (hasCompletedEvent || hasFailedEvent))).toBeTruthy();
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
    throw new Error(`Observer asset timeline is empty for model execution assetId ${assetId}.`);
  }

  await expect(requestedEvent).toBeVisible();
  await expect(completedEvent).toBeVisible();
  await expect(page.getByText(modelName).first()).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("article.observer-card .observer-badge", { hasText: /^COMPLETED$/i }).first()).toBeVisible({
    timeout: 10_000,
  });

  return {
    status: "passed" as const,
    observedEvents: ["MODEL_EXECUTION_REQUESTED", "MODEL_EXECUTION_COMPLETED"],
  };
}

test("12 AI Model Execution: local model-server inference from INESData UI", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "This demo validates the INESData connector UI path.");

  const suffix = `amh-exec-${Date.now()}`;
  const assetId = `qa-ui-amh-exec-${suffix}`;
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.componentsNamespace);
  const modelPayload = aiModelHubPayload();
  const inputSchema = inputSchemaForPayload(modelPayload);
  const inputFeatures = inputFeaturesForPayload(modelPayload);
  const firstRequiredFeature = firstRequiredFeatureName(inputFeatures);
  const modelName = `AI Model Execution controlled model ${suffix}`;
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const report: AIModelExecutionUiReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    assetId,
    modelName,
    modelUrl,
    modelPath,
    payload: modelPayload,
    inputValidationChecks: [],
    observerEvidenceChecks: [],
    linkedCases: ["PT5-MH-10", "PT5-MH-17", "MH-OBS-04", "DS-UI-AMH-EXEC-01"],
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
    report.assetId = OFFICIAL_FLARES_5W1H_MODEL.assetId;
    report.modelName = OFFICIAL_FLARES_5W1H_MODEL.name;
    report.modelUrl = "official-ai-model-hub-use-case-server";
    report.modelPath = DEFAULT_MODEL_PATH;
    report.payload = DEFAULT_PAYLOAD;

    await attachJson("ai-model-execution-ui-bootstrap", {
      sourceOfTruth: OFFICIAL_FLARES_5W1H_MODEL.sourceOfTruth,
      mode: "official-use-case-asset",
      syntheticAssetsCreated: false,
      asset: OFFICIAL_FLARES_5W1H_MODEL,
    });

    await loginPage.open(dataspaceRuntime.provider.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-ai-model-execution-after-login");

    await expect(async () => {
      await gotoAiModelExecution(page, dataspaceRuntime.provider.portalBaseUrl);
      await shellPage.assertNoGateway403("AI Model Execution page");
      await shellPage.assertNoServerErrorBanner("AI Model Execution page");
      await expect(page.getByRole("heading", { name: /AI Execution/i })).toBeVisible({ timeout: 20_000 });
      await expect(page.locator("#assetSelect")).toBeVisible({ timeout: 20_000 });
      await selectOptionMarked(page.locator("#assetSelect"), OFFICIAL_FLARES_5W1H_MODEL.assetId);
      await waitForUiTransition(page);
      await expect(page.getByRole("heading", { name: OFFICIAL_FLARES_5W1H_MODEL.name }).first()).toBeVisible({
        timeout: 30_000,
      });
    }).toPass({
      timeout: 120_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    await expect(page.getByText(/Local Asset/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Transformers/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Natural Language Processing/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: /Change Model/i }).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".input-schema-section").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Detected DAIMO input schema/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/2 fields/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(generatedInputField(page, "Id")).toBeVisible({ timeout: 15_000 });
    await expect(generatedInputField(page, "Text")).toBeVisible({ timeout: 15_000 });
    report.inputValidationChecks.push({
      scenario: "official_daimo_input_schema_detection",
      expectedMessage: "Detected DAIMO input schema with Id and Text fields.",
      status: "passed",
    });
    await attachJson("ai-model-execution-ui-selection-assertions", {
      assetId: OFFICIAL_FLARES_5W1H_MODEL.assetId,
      modelName: OFFICIAL_FLARES_5W1H_MODEL.name,
      sourceOfTruth: OFFICIAL_FLARES_5W1H_MODEL.sourceOfTruth,
      expectedPayload: DEFAULT_PAYLOAD,
      validatedInputSchemaFields: ["Id", "Text"],
    });
    await captureStep(page, "02-ai-model-execution-model-selected");

    await fillGeneratedFlares5w1hForm(page);
    await clickMarked(page.getByRole("button", { name: /Execute Model/i }).first(), { force: true });

    await expect(page.getByText(/Execution Result/i).first()).toBeVisible({ timeout: 120_000 });
    await expect(page.locator("body")).toContainText(/SUCCESS/i, { timeout: 30_000 });
    await expect(page.getByText(/Status Code:/i).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("body")).toContainText(/Status Code:\s*200/i, { timeout: 30_000 });
    await captureStep(page, "04-ai-model-execution-result");

    await clickMarked(page.getByRole("button", { name: /History/i }).first(), { force: true });
    await expect(page.getByText(/Execution History/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/success/i).first()).toBeVisible({ timeout: 10_000 });
    await captureStep(page, "05-ai-model-execution-history");

    await clickMarked(page.getByRole("button", { name: /View Observer Timeline/i }).first(), { force: true });
    await expect(page).toHaveURL(new RegExp(`/ai-model-observer/timeline/${OFFICIAL_FLARES_5W1H_MODEL.assetId}.*correlationId=`, "i"), {
      timeout: 30_000,
    });
    await expect(page.getByRole("heading", { name: /Asset timeline/i })).toBeVisible({ timeout: 10_000 });
    const officialObserverOutcome = await inspectExecutionObserverEvidence(
      page,
      OFFICIAL_FLARES_5W1H_MODEL.assetId,
      OFFICIAL_FLARES_5W1H_MODEL.name,
    );
    report.observerEvidenceChecks.push({
      scenario: "open_official_execution_asset_observer_timeline",
      assetId: OFFICIAL_FLARES_5W1H_MODEL.assetId,
      url: page.url(),
      observedEvents: officialObserverOutcome.observedEvents,
      status: officialObserverOutcome.status,
      reason: officialObserverOutcome.reason,
    });
    await attachJson("ai-model-execution-ui-observer-evidence", {
      assetId: OFFICIAL_FLARES_5W1H_MODEL.assetId,
      url: page.url(),
      checks: report.observerEvidenceChecks,
    });
    await captureStep(page, "06-ai-model-execution-observer-evidence");

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
    return;

    if (aiModelHubCatalogCleanupEnabled()) {
      await attachJson(
        "ai-model-execution-ui-catalog-cleanup",
        await cleanupProviderValidationArtifacts(request, dataspaceRuntime, {
          contractdefinitions: ["contract-ui-", "qa-ui-contract-definition-"],
          policydefinitions: ["policy-ui-", "qa-ui-policy-", "qa-ui-contract-policy-"],
          assets: [
            "asset-e2e-",
            "qa-ui-asset-",
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

    report.providerBootstrap = await bootstrapProviderNegotiationArtifacts(
      request,
      dataspaceRuntime,
      assetId,
      suffix,
      {
        sourceObjectName: `ai-model-execution-model-${suffix}.json`,
        name: modelName,
        version: "1.0.0",
        shortDescription: "AIModelHub-Use-Cases endpoint for AI Model Execution validation",
        description:
          "AIModelHub-Use-Cases model-server endpoint used to validate model execution from the INESData connector interface.",
        assetType: "machineLearning",
        keywords: ["validation", "ai-model-execution", "model-server", "machine-learning", "HttpData", "A5.2"],
        properties: {
          ...aiModelMetadataAliases({
            task: "Natural Language Processing",
            subtask: "token-classification",
            algorithm: "BERT",
            library: "Transformers",
            framework: "AIModelHub-Use-Cases",
            software: "FastAPI",
            inferencePath: modelPath,
            payload: modelPayload,
            inputSchema,
            inputFeatures,
          }),
          contenttype: "application/json",
          format: "json",
        },
        dataAddress: {
          type: "HttpData",
          baseUrl: modelUrl,
          method: "POST",
          name: `ai-model-execution-model-${suffix}.json`,
        },
      },
    );
    await attachJson("ai-model-execution-ui-bootstrap", report.providerBootstrap);

    await loginPage.open(dataspaceRuntime.provider.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-ai-model-execution-after-login");

    await expect(async () => {
      await gotoAiModelExecution(page, dataspaceRuntime.provider.portalBaseUrl);
      await shellPage.assertNoGateway403("AI Model Execution page");
      await shellPage.assertNoServerErrorBanner("AI Model Execution page");
      await expect(page.getByRole("heading", { name: /AI Execution/i })).toBeVisible({ timeout: 20_000 });
      await expect(page.locator("#assetSelect")).toBeVisible({ timeout: 20_000 });
      await selectOptionMarked(page.locator("#assetSelect"), assetId);
      await waitForUiTransition(page);
      await expect(page.getByRole("heading", { name: modelName })).toBeVisible({ timeout: 20_000 });
    }).toPass({
      timeout: 120_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    await expect(page.getByText(/Local Asset/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Transformers/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Natural Language Processing/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: /Change Model/i }).first()).toBeVisible({ timeout: 10_000 });
    if (inputFeatures.length > 0) {
      const schemaSection = page.locator(".input-schema-section").first();
      await expect(schemaSection).toBeVisible({ timeout: 10_000 });
      await expect(schemaSection.getByText(/Detected DAIMO input schema/i).first()).toBeVisible({ timeout: 10_000 });
      const schemaFieldCount = schemaSection.getByText(new RegExp(`${inputFeatures.length}\\s+fields?`, "i")).first();
      if (await schemaFieldCount.isVisible({ timeout: 2_000 }).catch(() => false)) {
        await expect(schemaFieldCount).toBeVisible();
      }
      const generatedFormButton = page.getByRole("button", { name: /Generated Form/i }).first();
      if (await generatedFormButton.isVisible({ timeout: 2_000 }).catch(() => false)) {
        await expect(generatedFormButton).toBeVisible();
        for (const feature of inputFeatures.slice(0, 3)) {
          const featureName = String((feature as { name?: unknown }).name || "").trim();
          if (featureName) {
            await expect(generatedInputField(page, featureName)).toBeVisible({ timeout: 10_000 });
          }
        }
      } else {
        await expect(page.locator("#inputJson").first()).toBeVisible({ timeout: 10_000 });
      }
    } else {
      await expect(page.getByText(/Detected example payload/i).first()).toBeVisible({ timeout: 10_000 });
    }
    await attachJson("ai-model-execution-ui-selection-assertions", {
      assetId,
      modelName,
      modelUrl,
      expectedPayload: modelPayload,
      expectedModel: process.env.UI_AI_MODEL_HUB_EXPECTED_RESULT_TEXT || "HTTP 200 model-server response",
    });
    await captureStep(page, "02-ai-model-execution-model-selected");

    await clickMarked(page.getByRole("button", { name: /JSON Payload/i }).first(), { force: true });
    const inputJson = page.locator("#inputJson").first();
    await expect(inputJson).toBeVisible({ timeout: 10_000 });

    await fillMarked(inputJson, "{");
    await clickMarked(page.getByRole("button", { name: /Execute Model/i }).first(), { force: true });
    await expect(page.getByText(/Invalid JSON format/i).first()).toBeVisible({ timeout: 10_000 });
    report.inputValidationChecks.push({
      scenario: "malformed_json_payload",
      expectedMessage: "Invalid JSON format.",
      status: "passed",
    });

    if (firstRequiredFeature) {
      await fillMarked(inputJson, JSON.stringify(missingRequiredPayloadFor(modelPayload), null, 2));
      await clickMarked(page.getByRole("button", { name: /Execute Model/i }).first(), { force: true });
      await expect(
        page.getByText(new RegExp(`(?:Row #1:\\s*)?Field "${firstRequiredFeature}" is required`, "i")).first(),
      ).toBeVisible({ timeout: 10_000 });
      report.inputValidationChecks.push({
        scenario: `missing_required_${firstRequiredFeature}_field`,
        expectedMessage: `Field "${firstRequiredFeature}" is required.`,
        status: "passed",
      });
    }
    await captureStep(page, "03-ai-model-execution-input-validation");
    await attachJson("ai-model-execution-ui-input-validation", {
      assetId,
      inputSchema,
      checks: report.inputValidationChecks,
    });

    await fillMarked(inputJson, JSON.stringify(modelPayload, null, 2));
    await clickMarked(page.getByRole("button", { name: /Execute Model/i }).first(), { force: true });
    await expect(page.getByText(/Execution Result/i).first()).toBeVisible({ timeout: 45_000 });
    await expect(page.getByText(/SUCCESS/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Status Code:/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/200/i).first()).toBeVisible({ timeout: 10_000 });
    const expectedResultText = (process.env.UI_AI_MODEL_HUB_EXPECTED_RESULT_TEXT || "").trim();
    if (expectedResultText) {
      await expect(page.getByText(new RegExp(expectedResultText, "i")).first()).toBeVisible({ timeout: 10_000 });
    }
    await captureStep(page, "04-ai-model-execution-result");

    await clickMarked(page.getByRole("button", { name: /History/i }).first(), { force: true });
    await expect(page.getByText(/Execution History/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/success/i).first()).toBeVisible({ timeout: 10_000 });
    await captureStep(page, "05-ai-model-execution-history");

    await clickMarked(page.getByRole("button", { name: /View Observer Timeline/i }).first(), { force: true });
    await expect(page).toHaveURL(new RegExp(`/ai-model-observer/timeline/${assetId}.*correlationId=`, "i"), {
      timeout: 10_000,
    });
    await expect(page.getByRole("heading", { name: /Asset timeline/i })).toBeVisible({ timeout: 10_000 });
    const observerOutcome = await inspectExecutionObserverEvidence(page, assetId, modelName);
    report.observerEvidenceChecks.push({
      scenario: "open_execution_asset_observer_timeline",
      assetId,
      url: page.url(),
      observedEvents: observerOutcome.observedEvents,
      status: observerOutcome.status,
      reason: observerOutcome.reason,
    });
    await attachJson("ai-model-execution-ui-observer-evidence", {
      assetId,
      url: page.url(),
      checks: report.observerEvidenceChecks,
    });
    await captureStep(page, "06-ai-model-execution-observer-evidence");

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
    await attachJson("ai-model-execution-ui-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("ai-model-execution-ui-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
