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
} from "../../../shared/utils/provider-bootstrap";
import { EVENTUAL_UI_RETRY_INTERVALS } from "../../../shared/utils/waiting";

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
  consumerAgreement?: {
    agreementId: string | null;
    assetId: string;
    attempts: number;
  };
};

const DEFAULT_MODEL_PATH = "/api/v1/nlp/ecommerce-sentiment";

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

function aiModelHubModelUrl(dataspace: string): string {
  const explicit = (process.env.UI_AI_MODEL_HUB_MODEL_URL || "").trim();
  if (explicit) {
    return explicit;
  }

  return `http://model-server.${dataspace}.svc.cluster.local:8080${aiModelHubModelPath()}`;
}

function aiModelHubCatalogCleanupEnabled(): boolean {
  return process.env.UI_AI_MODEL_HUB_CATALOG_CLEANUP === "1";
}

test("09 AI Model Hub HttpData: visible model discovery and negotiation from INESData UI", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.skip(dataspaceRuntime.adapter !== "inesdata", "This demo validates the INESData connector UI path.");

  const suffix = `amh-${Date.now()}`;
  const assetId = `qa-ui-amh-httpdata-${suffix}`;
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.dataspace);
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
  };

  const isTolerableCatalogRetry = (url: string, status: number): boolean =>
    (status === 401 || status === 503) &&
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
        assetType: "ai-model-execution-endpoint",
        keywords: ["validation", "ai-model-hub", "machine-learning", "HttpData", "A5.2"],
        properties: {
          "daimo:asset_kind": "model",
          "daimo:task": "text-classification",
          "daimo:framework": "controlled-httpdata",
          "daimo:inference_path": modelPath,
        },
        dataAddress: {
          type: "HttpData",
          baseUrl: modelUrl,
          method: "POST",
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
      await catalogPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
      await shellPage.assertNoGateway403("AI Model Hub catalog page");
      await shellPage.assertNoServerErrorBanner("AI Model Hub catalog page");
      await catalogPage.expectReady();
      await catalogPage.showLargestPageSize();

      let opened = await catalogPage.openDetailsForAsset(assetId);
      while (!opened && (await catalogPage.goToNextPage())) {
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

    await contractOffersPage.negotiateFirstOffer();
    report.negotiationMessage = await contractOffersPage.waitForNegotiationComplete(45_000);
    await captureStep(page, "04-ai-model-hub-httpdata-negotiation-complete");

    expect(report.negotiationMessage, "No completed negotiation notification was detected").toMatch(
      /contract negotiation complete!/i,
    );
    const consumerAgreement = await waitForConsumerAgreement(request, dataspaceRuntime, assetId, 20, 1_500);
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
