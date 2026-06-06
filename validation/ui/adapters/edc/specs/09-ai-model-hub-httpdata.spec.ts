import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import {
  bootstrapConsumerNegotiation,
  bootstrapProviderNegotiationArtifacts,
  probeConsumerCatalogDatasetReadiness,
  waitForConsumerAgreement,
} from "../../../shared/utils/provider-bootstrap";
import { EdcContractsPage } from "../components/edc-contracts.page";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import { EdcMlAssetsPage } from "../components/edc-ml-components.page";
import {
  aiModelAssetOptions,
  aiModelHubModelPath,
  aiModelHubModelUrl,
} from "../utils/edc-component-fixtures";

type AIModelHubEdcReport = {
  startedAt: string;
  providerConnector: string;
  consumerConnector: string;
  assetId: string;
  modelName: string;
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

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 to validate AI Model Hub HttpData assets through the EDC dashboard.",
);

test("09 edc AI Model Hub HttpData: visible model discovery and negotiation", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(300_000);

  const suffix = `amh-edc-${Date.now()}`;
  const assetId = `qa-ui-edc-amh-httpdata-${suffix}`;
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.componentsNamespace);
  const modelName = `EDC AI Model Hub HttpData model ${suffix}`;
  const report: AIModelHubEdcReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    consumerConnector: dataspaceRuntime.consumer.connectorName,
    assetId,
    modelName,
    modelUrl,
    modelPath,
    linkedCases: ["PT5-MH-03", "PT5-MH-08", "PT5-MH-09", "PT5-MH-10", "DS-UI-AMH-EDC-01"],
    errorResponses: [],
  };

  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);
  const mlAssetsPage = new EdcMlAssetsPage(page);
  const contractsPage = new EdcContractsPage(page);

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
      aiModelAssetOptions({ suffix, modelUrl, modelPath, modelName }),
    );
    await attachJson("edc-ai-model-hub-httpdata-bootstrap", report.providerBootstrap);
    const readiness = await probeConsumerCatalogDatasetReadiness(request, dataspaceRuntime, assetId);
    await attachJson("edc-ai-model-hub-httpdata-catalog-api-readiness", readiness);
    expect(
      readiness.status,
      `AI Model Hub asset ${assetId} was not ready in the catalog API: ${readiness.error || "unknown error"}`,
    ).toBe("ready");

    await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-ai-model-hub-after-login");

    await mlAssetsPage.goto(dataspaceRuntime.consumer.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC AI Model Hub browser");
    await mlAssetsPage.expectReady();
    await mlAssetsPage.waitForAssetVisible(assetId, 120_000);
    await captureStep(page, "02-edc-ai-model-hub-browser");

    report.consumerNegotiation = await bootstrapConsumerNegotiation(
      request,
      dataspaceRuntime,
      assetId,
      dataspaceRuntime.provider.protocolBaseUrl,
      dataspaceRuntime.provider.connectorName,
    );
    report.consumerAgreement = await waitForConsumerAgreement(request, dataspaceRuntime, assetId, 40, 1_500);
    await dashboardPage.navigateToSection("Contracts", "/edc-dashboard/contracts");
    await contractsPage.expectReady();
    await contractsPage.waitForContractVisible(assetId, 120_000);
    await captureStep(page, "03-edc-ai-model-hub-contract");

    expect(report.consumerAgreement.agreementId, "No consumer agreement was found for the model asset").toBeTruthy();
    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during AI Model Hub discovery: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-ai-model-hub-httpdata-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
