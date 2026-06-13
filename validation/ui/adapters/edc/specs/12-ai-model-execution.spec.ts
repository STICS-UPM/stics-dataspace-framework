import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { bootstrapProviderNegotiationArtifacts } from "../../../shared/utils/provider-bootstrap";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import { EdcModelExecutionPage } from "../components/edc-ml-components.page";
import {
  aiModelAssetOptions,
  aiModelHubModelPath,
  aiModelHubModelUrl,
  DEFAULT_AI_MODEL_PAYLOAD,
} from "../utils/edc-component-fixtures";

type AIModelExecutionEdcReport = {
  startedAt: string;
  providerConnector: string;
  assetId: string;
  modelUrl: string;
  modelPath: string;
  payload: Record<string, unknown>;
  linkedCases: string[];
  errorResponses: Array<{ url: string; status: number }>;
};

const modelServerSkipReason =
  process.env.UI_AI_MODEL_HUB_MODEL_SERVER_SKIP_REASON ||
  "AI Model Hub model-server is not deployed for this topology; skipping execution-dependent EDC dashboard validation.";

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 to validate AI Model Execution through the EDC dashboard.",
);

test.skip(
  process.env.UI_AI_MODEL_HUB_MODEL_SERVER_DEMO === "0" ||
    process.env.UI_AI_MODEL_HUB_MODEL_SERVER_COVERAGE_STATUS === "skipped_model_server_not_deployed",
  modelServerSkipReason,
);

test("12 edc AI Model Execution: local model endpoint inference from dashboard", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  test.setTimeout(300_000);

  const suffix = `amh-exec-edc-${Date.now()}`;
  const assetId = `qa-ui-edc-amh-exec-${suffix}`;
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.componentsNamespace);
  const report: AIModelExecutionEdcReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    assetId,
    modelUrl,
    modelPath,
    payload: DEFAULT_AI_MODEL_PAYLOAD,
    linkedCases: ["PT5-MH-10", "PT5-MH-17", "DS-UI-AMH-EXEC-EDC-01"],
    errorResponses: [],
  };

  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
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
    await bootstrapProviderNegotiationArtifacts(
      request,
      dataspaceRuntime,
      assetId,
      suffix,
      aiModelAssetOptions({ suffix, modelUrl, modelPath, modelName: `EDC execution model ${suffix}` }),
    );

    await loginPage.open(dataspaceRuntime.provider.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-ai-model-execution-after-login");

    await executionPage.goto(dataspaceRuntime.provider.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC AI Model Execution");
    await executionPage.expectReady();
    await executionPage.waitForExecutableAsset(assetId, 120_000);
    await captureStep(page, "02-edc-ai-model-execution-asset");

    await executionPage.executeAsset(assetId, DEFAULT_AI_MODEL_PAYLOAD);
    await captureStep(page, "03-edc-ai-model-execution-output");

    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during AI Model Execution: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-ai-model-execution-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
