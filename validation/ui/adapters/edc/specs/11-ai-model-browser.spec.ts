import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { bootstrapProviderNegotiationArtifacts } from "../../../shared/utils/provider-bootstrap";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import { EdcMlAssetsPage } from "../components/edc-ml-components.page";
import {
  aiModelAssetOptions,
  aiModelHubModelPath,
  aiModelHubModelUrl,
} from "../utils/edc-component-fixtures";

type AIModelBrowserEdcReport = {
  startedAt: string;
  providerConnector: string;
  modelAssetId: string;
  comparisonAssetId: string;
  modelUrl: string;
  modelPath: string;
  linkedCases: string[];
  errorResponses: Array<{ url: string; status: number }>;
};

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 to validate AI Model Browser through the EDC dashboard.",
);

test("11 edc AI Model Browser: model cards and search filters are rendered", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `amh-browser-edc-${Date.now()}`;
  const modelAssetId = `qa-ui-edc-amh-browser-${suffix}`;
  const comparisonAssetId = `qa-ui-edc-amh-browser-alt-${suffix}`;
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.componentsNamespace);
  const report: AIModelBrowserEdcReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    modelAssetId,
    comparisonAssetId,
    modelUrl,
    modelPath,
    linkedCases: ["PT5-MH-08", "PT5-MH-09", "PT5-MH-17", "DS-UI-AMH-BROWSER-EDC-01"],
    errorResponses: [],
  };

  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);
  const mlAssetsPage = new EdcMlAssetsPage(page);

  page.on("response", (response) => {
    const url = response.url();
    if (response.status() >= 400 && url.includes("/edc-dashboard-api/")) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    await bootstrapProviderNegotiationArtifacts(
      request,
      dataspaceRuntime,
      modelAssetId,
      suffix,
      aiModelAssetOptions({
        suffix,
        modelUrl,
        modelPath,
        modelName: `EDC AI Model Browser sentiment model ${suffix}`,
      }),
    );
    await bootstrapProviderNegotiationArtifacts(
      request,
      dataspaceRuntime,
      comparisonAssetId,
      `${suffix}-alt`,
      aiModelAssetOptions({
        suffix: `${suffix}-alt`,
        modelUrl,
        modelPath,
        modelName: `EDC AI Model Browser forecast model ${suffix}`,
        task: "time-series-regression",
        subtask: "demand-forecasting",
        algorithm: "controlled-forecast",
      }),
    );

    await loginPage.open(dataspaceRuntime.provider.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-ai-model-browser-after-login");

    await mlAssetsPage.goto(dataspaceRuntime.provider.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC AI Model Browser");
    await mlAssetsPage.expectReady();
    await mlAssetsPage.waitForAssetVisible(modelAssetId, 120_000);
    await mlAssetsPage.search(comparisonAssetId);
    await mlAssetsPage.waitForAssetVisible(comparisonAssetId, 60_000);
    await mlAssetsPage.expectAssetHidden(modelAssetId);
    await mlAssetsPage.search(modelAssetId);
    await mlAssetsPage.waitForAssetVisible(modelAssetId, 60_000);
    await captureStep(page, "02-edc-ai-model-browser-filtered");

    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during AI Model Browser validation: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-ai-model-browser-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
