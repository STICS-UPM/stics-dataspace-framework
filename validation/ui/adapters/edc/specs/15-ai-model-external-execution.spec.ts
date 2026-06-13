import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import {
  bootstrapConsumerNegotiation,
  bootstrapProviderNegotiationArtifacts,
  probeConsumerCatalogDatasetReadiness,
  waitForConsumerAgreement,
} from "../../../shared/utils/provider-bootstrap";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import { EdcModelExecutionPage } from "../components/edc-ml-components.page";
import {
  aiModelAssetOptions,
  aiModelHubModelPath,
  aiModelHubModelUrl,
  DEFAULT_AI_MODEL_PAYLOAD,
} from "../utils/edc-component-fixtures";

type AIModelExternalExecutionEdcReport = {
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
  consumerNegotiation?: {
    negotiationId: string;
    agreementId: string;
    assetId: string;
  };
  consumerAgreement?: {
    agreementId: string | null;
    assetId: string;
    attempts: number;
  };
  errorResponses: Array<{ url: string; status: number }>;
};

const modelServerSkipReason =
  process.env.UI_AI_MODEL_HUB_MODEL_SERVER_SKIP_REASON ||
  "AI Model Hub model-server is not deployed for this topology; skipping external execution-dependent EDC dashboard validation.";

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 to validate external AI Model execution through the EDC dashboard.",
);

test.skip(
  process.env.UI_AI_MODEL_HUB_MODEL_SERVER_DEMO === "0" ||
    process.env.UI_AI_MODEL_HUB_MODEL_SERVER_COVERAGE_STATUS === "skipped_model_server_not_deployed",
  modelServerSkipReason,
);

test("15 edc AI Model External Execution: negotiated model is executable by consumer", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(360_000);

  const suffix = `amh-external-edc-${Date.now()}`;
  const assetId = `qa-ui-edc-amh-external-${suffix}`;
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.componentsNamespace);
  const report: AIModelExternalExecutionEdcReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    consumerConnector: dataspaceRuntime.consumer.connectorName,
    assetId,
    modelUrl,
    modelPath,
    linkedCases: ["PT5-MH-10", "PT5-MH-17", "DS-UI-AMH-EXTERNAL-EDC-01"],
    errorResponses: [],
  };

  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);
  const executionPage = new EdcModelExecutionPage(page);

  page.on("response", (response) => {
    const url = response.url();
    if (response.status() >= 400 && url.includes("/edc-dashboard-api/")) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    report.providerBootstrap = await bootstrapProviderNegotiationArtifacts(
      request,
      dataspaceRuntime,
      assetId,
      suffix,
      aiModelAssetOptions({ suffix, modelUrl, modelPath, modelName: `EDC external execution model ${suffix}` }),
    );
    await attachJson("edc-ai-model-external-bootstrap", report.providerBootstrap);
    const readiness = await probeConsumerCatalogDatasetReadiness(request, dataspaceRuntime, assetId);
    await attachJson("edc-ai-model-external-catalog-api-readiness", readiness);
    expect(
      readiness.status,
      `External model asset ${assetId} was not ready in the catalog API: ${readiness.error || "unknown error"}`,
    ).toBe("ready");

    report.consumerNegotiation = await bootstrapConsumerNegotiation(
      request,
      dataspaceRuntime,
      assetId,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );
    report.consumerAgreement = await waitForConsumerAgreement(request, dataspaceRuntime, assetId, 40, 1_500);
    expect(report.consumerAgreement.agreementId, "No consumer agreement was found for the external model").toBeTruthy();

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-ai-model-external-after-login");

    await executionPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC external AI Model Execution");
    await executionPage.expectReady();
    await executionPage.waitForExecutableAsset(assetId, 120_000);
    await captureStep(page, "02-edc-ai-model-external-asset");

    await executionPage.executeAsset(assetId, DEFAULT_AI_MODEL_PAYLOAD);
    await captureStep(page, "03-edc-ai-model-external-output");

    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during external AI Model execution: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-ai-model-external-execution-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
