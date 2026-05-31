import type { Page } from "@playwright/test";

import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import { clickMarked, fillMarked, selectOptionMarked } from "../../../shared/utils/live-marker";
import {
  bootstrapConsumerNegotiation,
  bootstrapProviderNegotiationArtifacts,
  cleanupProviderValidationArtifacts,
  probeConsumerEdrReadinessForAssetAgreement,
  probeConsumerCatalogDatasetReadiness,
  waitForConsumerAgreement,
} from "../../../shared/utils/provider-bootstrap";
import { EVENTUAL_UI_RETRY_INTERVALS, waitForUiTransition } from "../../../shared/utils/waiting";
import { modelServerUrlForPath } from "../../../shared/utils/model-server-url";

type AIModelExternalExecutionUiReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
  modelName: string;
  modelUrl: string;
  modelPath: string;
  payload: Record<string, unknown>;
  linkedCases: string[];
  providerBootstrap?: {
    assetId: string;
    policyId: string;
    contractDefinitionId: string;
  };
  catalogReadiness?: {
    status?: "ready" | "timeout";
    assetId: string;
    counterPartyAddress: string;
    counterPartyId: string;
    datasetId: string;
    offerId: string;
    datasetCount: number;
    error?: string;
  };
  consumerNegotiation?: {
    negotiationId: string;
    agreementId: string;
    assetId: string;
    state?: string;
  };
  consumerAgreement?: {
    agreementId: string | null;
    assetId: string;
    attempts: number;
  };
  edrReadinessEvidence: Array<{
    attempt: number;
    status?: "ready" | "timeout";
    assetId: string;
    agreementId: string;
    transferCount: number;
    transfers: Array<{
      transferId: string;
      state: string;
      assetId?: string;
      contractId?: string;
      transferType?: string;
      edrHttpStatus?: number;
      edrEndpointPresent: boolean;
      edrAuthorizationPresent: boolean;
    }>;
    error?: string;
  }>;
  observerEvidenceChecks: Array<{
    scenario: string;
    assetId: string;
    url: string;
    observedEvents: string[];
    status: "passed" | "skipped";
    reason?: string;
  }>;
  errorResponses: Array<{ url: string; status: number }>;
  toleratedErrorResponses: Array<{ url: string; status: number }>;
  fatalErrorResponses: Array<{ url: string; status: number }>;
};

const DEFAULT_MODEL_PATH = "/api/v1/nlp/twitter-sentiment";
const DEFAULT_PAYLOAD = {
  text: "This public model response is excellent and useful",
};
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

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 or run Level 6 with the INESData adapter to validate external AI Model Execution from the INESData UI.",
);

function normalizePath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return DEFAULT_MODEL_PATH;
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function aiModelHubModelPath(): string {
  return normalizePath(process.env.UI_AI_MODEL_HUB_EXTERNAL_MODEL_PATH || DEFAULT_MODEL_PATH);
}

function aiModelHubModelUrl(componentsNamespace: string): string {
  return modelServerUrlForPath(aiModelHubModelPath(), componentsNamespace, {
    explicitUrlEnv: "UI_AI_MODEL_HUB_EXTERNAL_MODEL_URL",
  });
}

function aiModelHubCatalogCleanupEnabled(): boolean {
  return process.env.UI_AI_MODEL_HUB_CATALOG_CLEANUP === "1";
}

function externalExecutionMaxAttempts(): number {
  const configured = Number.parseInt(process.env.UI_AI_MODEL_EXTERNAL_EXECUTION_ATTEMPTS || "", 10);
  if (Number.isFinite(configured) && configured > 0) {
    return configured;
  }
  return (process.env.UI_TOPOLOGY || "").trim().toLowerCase() === "vm-distributed" ? 6 : 4;
}

function externalExecutionSettleMs(): number {
  const configured = Number.parseInt(process.env.UI_AI_MODEL_EXTERNAL_EXECUTION_SETTLE_MS || "", 10);
  if (Number.isFinite(configured) && configured >= 0) {
    return configured;
  }
  return (process.env.UI_TOPOLOGY || "").trim().toLowerCase() === "vm-distributed" ? 5_000 : 1_000;
}

function externalExecutionTimeoutMs(): number {
  const configured = Number.parseInt(process.env.UI_AI_MODEL_EXTERNAL_EXECUTION_TIMEOUT_MS || "", 10);
  if (Number.isFinite(configured) && configured > 0) {
    return configured;
  }
  return Math.max(240_000, 120_000 + externalExecutionMaxAttempts() * 75_000);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
  const inputExample = JSON.stringify(DEFAULT_PAYLOAD);

  return {
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
    inputExample: DEFAULT_PAYLOAD,
  };
}

async function gotoAiModelExecution(page: Page, baseUrl: string): Promise<void> {
  await page.goto(`${baseUrl.replace(/\/$/, "")}/ai-model-execution`, {
    waitUntil: "domcontentloaded",
  });
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
    throw new Error(`Observer asset timeline is empty for external model execution assetId ${assetId}.`);
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

test("15 AI Model Execution: external model with negotiated agreement from INESData UI", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "This demo validates the INESData connector UI path.");
  test.setTimeout(externalExecutionTimeoutMs());

  const suffix = `amh-external-exec-${Date.now()}`;
  const assetId = `qa-ui-amh-external-exec-${suffix}`;
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.componentsNamespace);
  const modelName = `AI Model External Execution ${suffix}`;
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const report: AIModelExternalExecutionUiReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    consumerConnector: dataspaceRuntime.consumer.connectorName,
    assetId,
    modelName,
    modelUrl,
    modelPath,
    payload: DEFAULT_PAYLOAD,
    linkedCases: ["PT5-MH-10", "PT5-MH-11", "PT5-MH-17", "AMH-INTEG-EXEC-AGREED-02", "DS-UI-AMH-EXEC-02"],
    edrReadinessEvidence: [],
    observerEvidenceChecks: [],
    errorResponses: [],
    toleratedErrorResponses: [],
    fatalErrorResponses: [],
  };

  const isTolerableRuntimeRetry = (url: string, status: number): boolean => {
    if (
      (status === 401 || status === 500 || status === 502 || status === 503 || status === 504) &&
      (url.includes("/management/pagination/count") ||
        url.includes("/management/assets/request") ||
        url.includes("/management/federatedcatalog/request") ||
        url.includes("/management/contractagreements/request"))
    ) {
      return true;
    }

    return status === 400 && url.includes("/management/v3/modelexecutions/execute") && report.edrReadinessEvidence.length > 0;
  };

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
        "ai-model-external-execution-ui-catalog-cleanup",
        await cleanupProviderValidationArtifacts(request, dataspaceRuntime, {
          contractdefinitions: ["contract-ui-", "qa-ui-contract-definition-"],
          policydefinitions: ["policy-ui-", "qa-ui-policy-", "qa-ui-contract-policy-"],
          assets: [
            "asset-e2e-",
            "qa-ui-asset-",
            "qa-ui-amh-browser-",
            "qa-ui-amh-exec-",
            "qa-ui-amh-external-exec-",
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
        sourceObjectName: `ai-model-external-execution-model-${suffix}.json`,
        name: modelName,
        version: "1.0.0",
        shortDescription: "External deterministic model-server endpoint for AI Model Execution validation",
        description:
          "Controlled provider-side HttpData model used to validate consumer execution after contract negotiation from the INESData connector interface.",
        assetType: "machineLearning",
        keywords: ["validation", "ai-model-execution", "external-model", "contract-agreement", "HttpData", "A5.2"],
        properties: {
          ...aiModelMetadataAliases({
            task: "text-classification",
            subtask: "social-media-sentiment",
            algorithm: "deterministic-rule-engine",
            library: "flask",
            framework: "model-server",
            software: "pionera-validation-framework",
            inferencePath: modelPath,
          }),
          contenttype: "application/json",
          format: "json",
          method: "POST",
          path: modelPath,
        },
        dataAddress: {
          type: "HttpData",
          baseUrl: modelUrl,
          method: "POST",
          proxyBody: "true",
          name: `ai-model-external-execution-model-${suffix}.json`,
        },
      },
    );
    await attachJson("ai-model-external-execution-provider-bootstrap", report.providerBootstrap);

    report.catalogReadiness = await probeConsumerCatalogDatasetReadiness(
      request,
      dataspaceRuntime,
      assetId,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );
    await attachJson("ai-model-external-execution-catalog-readiness", report.catalogReadiness);

    report.consumerNegotiation = await bootstrapConsumerNegotiation(
      request,
      dataspaceRuntime,
      assetId,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );
    await attachJson("ai-model-external-execution-consumer-negotiation", report.consumerNegotiation);

    const consumerAgreement = await waitForConsumerAgreement(request, dataspaceRuntime, assetId, 30, 1_500);
    report.consumerAgreement = {
      agreementId: consumerAgreement.agreementId,
      assetId: consumerAgreement.assetId,
      attempts: consumerAgreement.attempts,
    };
    await attachJson("ai-model-external-execution-consumer-agreement", report.consumerAgreement);
    expect(report.consumerAgreement.agreementId, "No consumer contract agreement was found for the external model asset").toBeTruthy();

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-ai-model-external-execution-after-login");

    await expect(async () => {
      await gotoAiModelExecution(page, dataspaceRuntime.consumer.portalBaseUrl);
      await shellPage.assertNoGateway403("AI Model Execution page");
      await shellPage.assertNoServerErrorBanner("AI Model Execution page");
      await expect(page.getByRole("heading", { name: /AI Execution/i })).toBeVisible({ timeout: 20_000 });
      await expect(page.locator("#assetSelect")).toBeVisible({ timeout: 20_000 });
      await expect(page.locator("#assetSelect option").filter({ hasText: modelName })).toHaveCount(1, {
        timeout: 20_000,
      });
      await selectOptionMarked(page.locator("#assetSelect"), assetId);
      await waitForUiTransition(page);
      await expect(page.getByRole("heading", { name: modelName })).toBeVisible({ timeout: 20_000 });
    }).toPass({
      timeout: 180_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    await expect(page.getByText(/External Asset/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Agreement ready/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(dataspaceRuntime.provider.connectorName).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/^POST$/i).first()).toBeVisible({ timeout: 10_000 });
    await captureStep(page, "02-ai-model-external-execution-model-selected");
    await attachJson("ai-model-external-execution-selection-assertions", {
      assetId,
      modelName,
      modelUrl,
      expectedPayload: DEFAULT_PAYLOAD,
      expectedAgreementId: report.consumerAgreement.agreementId,
      expectedUiState: ["External Asset", "Agreement ready", dataspaceRuntime.provider.connectorName, "POST"],
    });

    const inputTab = page.getByRole("button", { name: /^(JSON Payload|Input)$/i }).first();
    if (await inputTab.isVisible().catch(() => false)) {
      await clickMarked(inputTab, { force: true });
    }
    const inputJsonById = page.locator("#inputJson").first();
    const inputJson = (await inputJsonById.count()) > 0
      ? inputJsonById
      : page.getByRole("textbox", { name: /Input JSON Payload/i }).first();
    await expect(inputJson).toBeVisible({ timeout: 10_000 });
    await fillMarked(inputJson, JSON.stringify(DEFAULT_PAYLOAD, null, 2));

    let lastExecutionIssue = "";
    for (let attempt = 1; attempt <= externalExecutionMaxAttempts(); attempt += 1) {
      const executeResponsePromise = page.waitForResponse(
        (response) => response.url().includes("/management/v3/modelexecutions/execute"),
        { timeout: 120_000 },
      );
      await clickMarked(page.getByRole("button", { name: /Execute Model/i }).first(), { force: true });
      const executeResponse = await executeResponsePromise;
      await expect(page.getByText(/Execution Result/i).first()).toBeVisible({ timeout: 90_000 });

      if (await page.getByText(/SUCCESS/i).first().isVisible().catch(() => false)) {
        lastExecutionIssue = "";
        break;
      }

      const edrTimeoutError = page.getByText(/Unable to resolve EDR for assetId/i).first();
      const agreementId = report.consumerAgreement.agreementId;
      if (!agreementId || !(await edrTimeoutError.isVisible().catch(() => false))) {
        lastExecutionIssue = `External execution attempt ${attempt} did not succeed and did not expose the recoverable EDR-readiness error.`;
        break;
      }

      const edrReadiness = await probeConsumerEdrReadinessForAssetAgreement(
        request,
        dataspaceRuntime,
        assetId,
        agreementId,
      );
      report.edrReadinessEvidence.push({ attempt, ...edrReadiness });
      await attachJson(`ai-model-external-execution-edr-readiness-attempt-${attempt}`, edrReadiness);
      lastExecutionIssue =
        `External execution attempt ${attempt} reached the connector EDR timeout; ` +
        `EDR readiness after the timeout: ${edrReadiness.status}.`;

      if (attempt < externalExecutionMaxAttempts()) {
        if (edrReadiness.status === "ready") {
          await sleep(externalExecutionSettleMs());
        }
        const inputTabRetry = page.getByRole("button", { name: /^(JSON Payload|Input)$/i }).first();
        if (await inputTabRetry.isVisible().catch(() => false)) {
          await clickMarked(inputTabRetry, { force: true });
          await waitForUiTransition(page);
        }
        await expect(
          page.getByRole("button", { name: /Execute Model/i }).first(),
          `Execute Model button did not become ready after attempt ${attempt} returned HTTP ${executeResponse.status()}`,
        ).toBeEnabled({ timeout: 30_000 });
      }
    }

    if (lastExecutionIssue) {
      throw new Error(
        `${lastExecutionIssue} The connector model execution API starts an internal transfer for every execution request; ` +
          "if every attempt times out before its own EDR appears, the connector needs a longer configurable EDR wait.",
      );
    }
    await expect(page.getByText(/SUCCESS/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Status Code:/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/200/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Twitter Sentiment Analyzer/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/positive/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/local-rule-engine/i).first()).toBeVisible({ timeout: 10_000 });
    await captureStep(page, "03-ai-model-external-execution-result");

    await clickMarked(page.getByRole("button", { name: /History/i }).first(), { force: true });
    await expect(page.getByText(/Execution History/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/success/i).first()).toBeVisible({ timeout: 10_000 });
    await captureStep(page, "04-ai-model-external-execution-history");

    await clickMarked(page.getByRole("button", { name: /View Observer Timeline/i }).first(), { force: true });
    await expect(page).toHaveURL(new RegExp(`/ai-model-observer/timeline/${assetId}.*correlationId=`, "i"), {
      timeout: 10_000,
    });
    await expect(page.getByRole("heading", { name: /Asset timeline/i })).toBeVisible({ timeout: 10_000 });
    const observerOutcome = await inspectExecutionObserverEvidence(page, assetId, modelName);
    report.observerEvidenceChecks.push({
      scenario: "open_external_execution_asset_observer_timeline",
      assetId,
      url: page.url(),
      observedEvents: observerOutcome.observedEvents,
      status: observerOutcome.status,
      reason: observerOutcome.reason,
    });
    await attachJson("ai-model-external-execution-observer-evidence", {
      assetId,
      url: page.url(),
      checks: report.observerEvidenceChecks,
    });
    await captureStep(page, "05-ai-model-external-execution-observer-evidence");

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
    await attachJson("ai-model-external-execution-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("ai-model-external-execution-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
