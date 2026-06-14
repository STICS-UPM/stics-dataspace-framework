import { test, expect } from "../../../shared/fixtures/dataspace.fixture";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { CatalogPage } from "../components/consumer/catalog.page";
import { ContractOffersPage } from "../components/consumer/contract-offers.page";
import { collectBrowserDiagnostics } from "../../../shared/utils/browser-diagnostics";
import {
  bootstrapProviderNegotiationArtifacts,
  cleanupProviderValidationArtifacts,
  probeConsumerCatalogDatasetReadiness,
  waitForConsumerAgreement,
  waitForConsumerNegotiationOutcome,
} from "../../../shared/utils/provider-bootstrap";
import { EVENTUAL_UI_RETRY_INTERVALS } from "../../../shared/utils/waiting";
import { modelServerUrlForPath } from "../../../shared/utils/model-server-url";

type AIModelHubUiReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
  modelUrl: string;
  modelPath: string;
  linkedCases: string[];
  providerBootstrap?: {
    assetId: string;
    policyId: string;
    contractDefinitionId: string;
  };
  errorResponses: Array<{ url: string; status: number }>;
  toleratedErrorResponses: Array<{ url: string; status: number }>;
  fatalErrorResponses: Array<{ url: string; status: number }>;
  negotiationMessage?: string;
  negotiationNotificationWarning?: string;
  uiNegotiationAttempts: Array<{
    attempt: number;
    response?: {
      url: string;
      status: number;
      negotiationId?: string;
      bodySnippet?: string;
    };
    notification?: string;
    notificationWarning?: string;
    outcome?: {
      negotiationId: string;
      agreementId: string;
      state: string;
      attempts: number;
      status: "agreement" | "terminated" | "timeout";
      errorDetail?: string;
    };
    retryReason?: string;
  }>;
  consumerAgreement?: {
    agreementId: string | null;
    assetId: string;
    attempts: number;
  };
};

const DEFAULT_MODEL_PATH = "/api/v1/nlp/ecommerce-sentiment";
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

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 or run Level 6 with the INESData adapter to validate an AI Model Hub HttpData model asset from the INESData UI.",
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

function aiModelHubModelUrl(componentsNamespace: string): string {
  return modelServerUrlForPath(aiModelHubModelPath(), componentsNamespace);
}

function aiModelHubCatalogCleanupEnabled(): boolean {
  return process.env.UI_AI_MODEL_HUB_CATALOG_CLEANUP === "1";
}

function aiModelHubNegotiationAttempts(): number {
  const configured = Number.parseInt(process.env.UI_AI_MODEL_HUB_NEGOTIATION_ATTEMPTS || "", 10);
  return Number.isFinite(configured) && configured > 0 ? configured : 3;
}

function aiModelHubHttpDataTimeoutMs(): number {
  const configured = Number.parseInt(process.env.UI_AI_MODEL_HUB_HTTPDATA_TIMEOUT_MS || "", 10);
  return Number.isFinite(configured) && configured > 0 ? configured : 540_000;
}

function aiModelMetadataAliases(inferencePath: string): Record<string, unknown> {
  const inputFeatures = JSON.stringify(TEXT_MODEL_INPUT_FEATURES);
  const inputSchema = JSON.stringify(TEXT_MODEL_INPUT_SCHEMA);
  const inputExample = JSON.stringify(TEXT_MODEL_INPUT_EXAMPLE);

  return {
    "daimo:asset_kind": "model",
    "daimo:task": "text-classification",
    "https://w3id.org/daimo/ns#task": "text-classification",
    "https://pionera.ai/edc/daimo#task": "text-classification",
    "daimo:subtask": "sentiment-analysis",
    "https://w3id.org/daimo/ns#subtask": "sentiment-analysis",
    "https://pionera.ai/edc/daimo#subtask": "sentiment-analysis",
    "daimo:algorithm": "controlled-baseline",
    "https://w3id.org/daimo/ns#algorithm": "controlled-baseline",
    "https://pionera.ai/edc/daimo#algorithm": "controlled-baseline",
    "daimo:library": "validation-fixture",
    "https://w3id.org/daimo/ns#library": "validation-fixture",
    "https://pionera.ai/edc/daimo#library": "validation-fixture",
    "daimo:framework": "controlled-httpdata",
    "https://w3id.org/daimo/ns#framework": "controlled-httpdata",
    "https://pionera.ai/edc/daimo#framework": "controlled-httpdata",
    "daimo:software": "pionera-validation-framework",
    "https://w3id.org/daimo/ns#software": "pionera-validation-framework",
    "https://pionera.ai/edc/daimo#software": "pionera-validation-framework",
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
    task: "text-classification",
    subtask: "sentiment-analysis",
    algorithm: "controlled-baseline",
    library: "validation-fixture",
    framework: "controlled-httpdata",
    software: "pionera-validation-framework",
    inference_path: inferencePath,
    inferencePath,
    input_features: inputFeatures,
    inputFeatures: TEXT_MODEL_INPUT_FEATURES,
    input_schema: inputSchema,
    inputSchema: TEXT_MODEL_INPUT_SCHEMA,
    input_example: inputExample,
    inputExample: TEXT_MODEL_INPUT_EXAMPLE,
  };
}

test("09 AI Model Hub HttpData: visible model discovery and negotiation from INESData UI", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "This demo validates the INESData connector UI path.");
  test.setTimeout(aiModelHubHttpDataTimeoutMs());

  const suffix = `amh-${Date.now()}`;
  const assetId = `qa-ui-amh-httpdata-${suffix}`;
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.componentsNamespace);
  const modelName = `AI Model Hub HttpData model ${suffix}`;
  const browserDiagnostics = collectBrowserDiagnostics(page);
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const catalogPage = new CatalogPage(page);
  const contractOffersPage = new ContractOffersPage(page);
  const report: AIModelHubUiReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    consumerConnector: dataspaceRuntime.consumer.connectorName,
    assetId,
    modelUrl,
    modelPath,
    linkedCases: ["PT5-MH-03", "PT5-MH-08", "PT5-MH-09", "PT5-MH-10", "PT5-MH-18", "DS-UI-AMH-01"],
    errorResponses: [],
    toleratedErrorResponses: [],
    fatalErrorResponses: [],
    uiNegotiationAttempts: [],
  };

  const isTolerableCatalogRetry = (url: string, status: number): boolean =>
    (status === 401 || status === 500 || status === 502 || status === 503 || status === 504) &&
    (url.includes("/management/pagination/count?type=federatedCatalog") ||
      url.includes("/management/federatedcatalog/request"));

  page.on("response", (response) => {
    const url = response.url();
    if (
      response.status() >= 400 &&
      (url.includes("/management/") ||
        url.includes("/federatedcatalog") ||
        url.includes("/contractnegotiations"))
    ) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    if (aiModelHubCatalogCleanupEnabled()) {
      await attachJson(
        "ai-model-hub-httpdata-ui-catalog-cleanup",
        await cleanupProviderValidationArtifacts(request, dataspaceRuntime, {
          contractdefinitions: ["contract-ui-", "qa-ui-contract-definition-"],
          policydefinitions: ["policy-ui-", "qa-ui-policy-", "qa-ui-contract-policy-"],
          assets: [
            "asset-e2e-",
            "qa-ui-asset-",
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
        sourceObjectName: `ai-model-hub-model-${suffix}.json`,
        name: modelName,
        version: "1.0.0",
        shortDescription: "AI Model Hub model endpoint exposed as HttpData for UI demo validation",
        description:
          "Machine-learning model endpoint governed through INESData as a contractual HttpData asset.",
        assetType: "machineLearning",
        keywords: ["validation", "ai-model-hub", "machine-learning", "HttpData", "A5.2"],
        properties: {
          ...aiModelMetadataAliases(modelPath),
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
          name: `ai-model-hub-model-${suffix}.json`,
        },
      },
    );
    await attachJson("ai-model-hub-httpdata-ui-bootstrap", report.providerBootstrap);
    const catalogApiReadiness = await probeConsumerCatalogDatasetReadiness(request, dataspaceRuntime, assetId);
    await attachJson("ai-model-hub-httpdata-ui-catalog-api-readiness", catalogApiReadiness);
    expect(
      catalogApiReadiness.status,
      `AI Model Hub HttpData asset ${assetId} was not ready in the catalog API before UI validation: ${catalogApiReadiness.error || "unknown error"}`,
    ).toBe("ready");

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-ai-model-hub-httpdata-after-login");

    await expect(async () => {
      await catalogPage.goto(dataspaceRuntime.consumer.portalBaseUrl, {
        catalogKind: "federated",
        expectedAssetId: assetId,
      });
      await shellPage.assertNoGateway403("AI Model Hub catalog page");
      await shellPage.assertNoServerErrorBanner("AI Model Hub catalog page");
      await catalogPage.expectReady();
      await catalogPage.showLargestPageSize({ catalogKind: "federated", expectedAssetId: assetId });

      let opened = await catalogPage.openDetailsForAsset(assetId);
      while (!opened && (await catalogPage.goToNextPage({ catalogKind: "federated", expectedAssetId: assetId }))) {
        opened = await catalogPage.openDetailsForAsset(assetId);
      }

      expect(opened, `AI Model Hub HttpData asset ${assetId} is not visible in the consumer catalog yet`).toBeTruthy();
    }).toPass({
      timeout: 180_000,
      intervals: EVENTUAL_UI_RETRY_INTERVALS,
    });

    await captureStep(page, "02-ai-model-hub-httpdata-catalog-detail");
    await catalogPage.expectDetailsVisible({
      assetId,
      attachJson,
      context: "ai-model-hub-httpdata-catalog-detail",
    });
    await expect(page.getByText(assetId, { exact: true }).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(modelName).first()).toBeVisible({ timeout: 10_000 });
    await attachJson("ai-model-hub-httpdata-ui-metadata-assertions", {
      assetId,
      modelName,
      modelPath,
      modelUrl,
      expectedAssetType: "ai-model-execution-endpoint",
      expectedTask: "text-classification",
    });
    await contractOffersPage.expectReady({
      assetId,
      attachJson,
      context: "ai-model-hub-httpdata-contract-offers",
    });
    await contractOffersPage.openContractOffersTab();
    await captureStep(page, "03-ai-model-hub-httpdata-contract-offers");

    let consumerAgreement: Awaited<ReturnType<typeof waitForConsumerAgreement>> | undefined;
    const maxNegotiationAttempts = aiModelHubNegotiationAttempts();

    for (let attempt = 1; attempt <= maxNegotiationAttempts; attempt += 1) {
      const attemptReport: AIModelHubUiReport["uiNegotiationAttempts"][number] = {
        attempt,
      };
      report.uiNegotiationAttempts.push(attemptReport);

      const notificationPromise = contractOffersPage.readNegotiationCompletionNotification(10_000);
      const submission = await contractOffersPage.negotiateFirstOfferAndWaitForSubmission(15_000);
      attemptReport.response = submission;

      if (!submission) {
        await attachJson(`ai-model-hub-httpdata-negotiation-attempt-${attempt}`, attemptReport);
        throw new Error(`No contract negotiation POST was observed after clicking Negotiate Contract on attempt ${attempt}`);
      }
      if (submission.status >= 400) {
        await attachJson(`ai-model-hub-httpdata-negotiation-attempt-${attempt}`, attemptReport);
        throw new Error(
          `Contract negotiation POST returned HTTP ${submission.status} on attempt ${attempt}: ${submission.bodySnippet || "<empty body>"}`,
        );
      }
      if (!submission.negotiationId) {
        await attachJson(`ai-model-hub-httpdata-negotiation-attempt-${attempt}`, attemptReport);
        throw new Error(
          `Contract negotiation response did not expose an identifier on attempt ${attempt}: ${submission.bodySnippet || "<empty body>"}`,
        );
      }

      const outcome = await waitForConsumerNegotiationOutcome(
        request,
        dataspaceRuntime,
        submission.negotiationId,
        45,
        1_000,
      );
      attemptReport.outcome = {
        negotiationId: outcome.negotiationId,
        agreementId: outcome.agreementId,
        state: outcome.state,
        attempts: outcome.attempts,
        status: outcome.status,
        errorDetail: outcome.errorDetail,
      };

      const notification = await notificationPromise;
      if (notification.message) {
        attemptReport.notification = notification.message;
        report.negotiationMessage = notification.message;
      } else if (notification.warning) {
        attemptReport.notificationWarning = notification.warning;
        report.negotiationNotificationWarning = notification.warning;
      }

      if (outcome.agreementId) {
        if (!report.negotiationMessage) {
          report.negotiationMessage = `Contract agreement ${outcome.agreementId} verified through consumer management API after UI negotiation.`;
        }
        await captureStep(page, "04-ai-model-hub-httpdata-negotiation-complete");
        consumerAgreement = await waitForConsumerAgreement(request, dataspaceRuntime, assetId, 20, 1_500);
        await attachJson(`ai-model-hub-httpdata-negotiation-attempt-${attempt}`, attemptReport);
        break;
      }

      attemptReport.retryReason =
        `Negotiation ${outcome.negotiationId} reached ${outcome.state} without contractAgreementId` +
        (outcome.errorDetail ? `: ${outcome.errorDetail}` : "");
      await attachJson(`ai-model-hub-httpdata-negotiation-attempt-${attempt}`, attemptReport);

      if (attempt < maxNegotiationAttempts) {
        await captureStep(page, `04-ai-model-hub-httpdata-negotiation-retry-${attempt}`);
        continue;
      }

      throw new Error(
        `AI Model Hub UI negotiation did not produce a contract agreement after ${maxNegotiationAttempts} attempt(s). ` +
          `Last outcome: ${JSON.stringify(attemptReport.outcome)}`,
      );
    }

    if (!consumerAgreement) {
      throw new Error("No consumer contract agreement was found for the model asset");
    }
    report.consumerAgreement = {
      agreementId: consumerAgreement.agreementId,
      assetId: consumerAgreement.assetId,
      attempts: consumerAgreement.attempts,
    };
    await attachJson("ai-model-hub-httpdata-contract-agreement", report.consumerAgreement);
    expect(report.consumerAgreement.agreementId, "No consumer contract agreement was found for the model asset").toBeTruthy();
    report.toleratedErrorResponses = report.errorResponses.filter(({ url, status }) =>
      isTolerableCatalogRetry(url, status),
    );
    report.fatalErrorResponses = report.errorResponses.filter(
      ({ url, status }) => !isTolerableCatalogRetry(url, status),
    );
    expect(
      report.fatalErrorResponses,
      `API calls returned fatal errors: ${JSON.stringify(report.fatalErrorResponses)} (tolerated transient catalog errors: ${JSON.stringify(report.toleratedErrorResponses)})`,
    ).toHaveLength(0);
  } finally {
    const browserDiagnosticsSnapshot = browserDiagnostics.snapshot();
    browserDiagnostics.dispose();
    await attachJson("ai-model-hub-httpdata-ui-browser-diagnostics", browserDiagnosticsSnapshot);
    await attachJson("ai-model-hub-httpdata-ui-report", {
      ...report,
      finishedAt: new Date().toISOString(),
      browserDiagnostics: {
        eventCount: browserDiagnosticsSnapshot.eventCount,
        droppedEventCount: browserDiagnosticsSnapshot.droppedEventCount,
      },
    });
  }
});
