import { KeycloakLoginPage } from "../../../components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { EdcAssetsPage } from "../components/edc-assets.page";
import { EdcDashboardPage } from "../components/edc-dashboard.page";

type ProviderAssetReport = {
  startedAt: string;
  providerConnector: string;
  assetId: string;
  sourceUrl: string;
  errorResponses: Array<{ url: string; status: number }>;
};

test("03 edc provider setup: asset creation from the UI", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-edc-asset-${suffix}`;
  const sourceUrl = `https://jsonplaceholder.typicode.com/todos/${(Number(suffix.slice(-3)) % 200) + 1}`;
  const report: ProviderAssetReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    assetId,
    sourceUrl,
    errorResponses: [],
  };

  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);
  const assetsPage = new EdcAssetsPage(page);

  page.on("response", (response) => {
    const url = response.url();
    if (response.status() >= 400 && url.includes("/edc-dashboard-api/")) {
      report.errorResponses.push({ url, status: response.status() });
    }
  });

  try {
    await loginPage.open(dataspaceRuntime.provider.portalBaseUrl);
    await loginPage.loginIfNeeded();
    await dashboardPage.expectShellReady();
    await captureStep(page, "01-edc-provider-asset-after-login");

    await assetsPage.goto(dataspaceRuntime.provider.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC provider assets");
    await assetsPage.expectReady();
    await assetsPage.createHttpAsset(assetId, sourceUrl);
    await assetsPage.waitForAssetListed(assetId);
    await captureStep(page, "02-edc-provider-asset-created");

    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during provider asset creation: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-provider-asset-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
