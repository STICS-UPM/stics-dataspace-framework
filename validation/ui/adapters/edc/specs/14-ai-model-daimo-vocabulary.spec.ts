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

type AIMetadataEdcReport = {
  startedAt: string;
  providerConnector: string;
  assetId: string;
  expectedTask: string;
  expectedFramework: string;
  linkedCases: string[];
  errorResponses: Array<{ url: string; status: number }>;
};

test.skip(
  process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO !== "1",
  "Set UI_AI_MODEL_HUB_HTTPDATA_DEMO=1 to validate DAIMO metadata rendering through the EDC dashboard.",
);

test("14 edc AI Model Hub DAIMO metadata: model metadata is rendered in ML Assets", async ({
  page,
  request,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `amh-daimo-edc-${Date.now()}`;
  const assetId = `qa-ui-edc-amh-daimo-${suffix}`;
  const expectedTask = "text-classification";
  const expectedFramework = "controlled-httpdata";
  const modelPath = aiModelHubModelPath();
  const modelUrl = aiModelHubModelUrl(dataspaceRuntime.componentsNamespace);
  const report: AIMetadataEdcReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    assetId,
    expectedTask,
    expectedFramework,
    linkedCases: ["PT5-MH-02", "PT5-MH-06", "PT5-MH-17", "DS-UI-AMH-DAIMO-EDC-01"],
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
      assetId,
      suffix,
      aiModelAssetOptions({
        suffix,
        modelUrl,
        modelPath,
        modelName: `EDC AI Model Hub DAIMO metadata model ${assetId}`,
      }),
    );

    await loginPage.open(dataspaceRuntime.provider.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-ai-model-daimo-after-login");

    await mlAssetsPage.goto(dataspaceRuntime.provider.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC AI Model DAIMO metadata");
    await mlAssetsPage.expectReady();
    await mlAssetsPage.waitForAssetVisible(assetId, 120_000);
    await mlAssetsPage.openDetails(assetId);
    const details = page.locator("app-ml-asset-details-modal").filter({ hasText: assetId }).first();
    await expect(details.getByText(expectedTask).first()).toBeVisible({ timeout: 30_000 });
    await expect(details.getByText(expectedFramework).first()).toBeVisible({ timeout: 30_000 });
    await captureStep(page, "02-edc-ai-model-daimo-card");

    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during DAIMO metadata validation: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-ai-model-daimo-metadata-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
