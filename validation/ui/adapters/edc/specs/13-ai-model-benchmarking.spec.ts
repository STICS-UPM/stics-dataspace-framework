import fs from "fs";

import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { bootstrapProviderNegotiationArtifacts } from "../../../shared/utils/provider-bootstrap";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import { EdcModelBenchmarkingPage } from "../components/edc-ml-components.page";
import {
  aiModelAssetOptions,
  aiModelHubModelPath,
  aiModelHubModelUrl,
  TEXT_MODEL_BENCHMARK_ROWS,
} from "../utils/edc-component-fixtures";

type AIModelBenchmarkingEdcReport = {
  startedAt: string;
  providerConnector: string;
  modelAssetIds: string[];
  modelUrl: string;
  modelPath: string;
  linkedCases: string[];
  errorResponses: Array<{ url: string; status: number }>;
};

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 to validate AI Model Benchmarking through the EDC dashboard.",
);

test("13 edc AI Model Benchmarking: compatible models and dataset validation", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}, testInfo) => {
  test.setTimeout(360_000);

  const suffix = `amh-benchmark-edc-${Date.now()}`;
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.componentsNamespace);
  const modelAssetIds = [
    `qa-ui-edc-amh-benchmark-a-${suffix}`,
    `qa-ui-edc-amh-benchmark-b-${suffix}`,
  ];
  const datasetPath = testInfo.outputPath("edc-ai-model-benchmark-dataset.json");
  fs.writeFileSync(datasetPath, JSON.stringify(TEXT_MODEL_BENCHMARK_ROWS, null, 2), "utf8");

  const report: AIModelBenchmarkingEdcReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    modelAssetIds,
    modelUrl,
    modelPath,
    linkedCases: ["PT5-MH-10", "PT5-MH-18", "DS-UI-AMH-BENCH-EDC-01"],
    errorResponses: [],
  };

  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);
  const benchmarkingPage = new EdcModelBenchmarkingPage(page);

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
      modelAssetIds[0],
      `${suffix}-a`,
      aiModelAssetOptions({
        suffix: `${suffix}-a`,
        modelUrl,
        modelPath,
        modelName: `EDC benchmark model A ${suffix}`,
      }),
    );
    await bootstrapProviderNegotiationArtifacts(
      request,
      dataspaceRuntime,
      modelAssetIds[1],
      `${suffix}-b`,
      aiModelAssetOptions({
        suffix: `${suffix}-b`,
        modelUrl,
        modelPath,
        modelName: `EDC benchmark model B ${suffix}`,
      }),
    );

    await loginPage.open(dataspaceRuntime.provider.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-ai-model-benchmarking-after-login");

    await benchmarkingPage.goto(dataspaceRuntime.provider.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC AI Model Benchmarking");
    await benchmarkingPage.expectReady();
    await benchmarkingPage.waitForExecutableAssets(modelAssetIds, 120_000);
    await benchmarkingPage.selectAssets(modelAssetIds);
    await benchmarkingPage.uploadDataset(datasetPath);
    await captureStep(page, "02-edc-ai-model-benchmarking-inputs");

    await benchmarkingPage.validateInput();
    await captureStep(page, "03-edc-ai-model-benchmarking-validation");

    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during AI Model Benchmarking: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-ai-model-benchmarking-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
