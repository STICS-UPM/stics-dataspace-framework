import { KeycloakLoginPage } from "../../../components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { EdcAssetsPage } from "../components/edc-assets.page";
import { EdcContractDefinitionsPage } from "../components/edc-contract-definitions.page";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import { EdcPoliciesPage } from "../components/edc-policies.page";

test.setTimeout(180_000);

type ProviderContractDefinitionReport = {
  startedAt: string;
  providerConnector: string;
  assetId: string;
  policyId: string;
  contractDefinitionId: string;
  sourceUrl: string;
  assetSelectionMode?: "all-assets";
  errorResponses: Array<{ url: string; status: number }>;
};

test("03c edc provider setup: contract definition creation from the UI", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const assetId = `qa-ui-edc-contract-asset-${suffix}`;
  const policyId = `qa-edc-policy-contract-${suffix}`;
  const contractDefinitionId = `qa-edc-contract-${suffix}`;
  const sourceUrl = `https://jsonplaceholder.typicode.com/todos/${(Number(suffix.slice(-3)) % 200) + 1}`;
  const report: ProviderContractDefinitionReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    assetId,
    policyId,
    contractDefinitionId,
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
  const policiesPage = new EdcPoliciesPage(page);
  const contractDefinitionsPage = new EdcContractDefinitionsPage(page);

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
    await captureStep(page, "01-edc-provider-contract-definition-after-login");

    await assetsPage.goto(dataspaceRuntime.provider.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC provider contract definition asset");
    await assetsPage.expectReady();
    await assetsPage.createHttpAsset(assetId, sourceUrl);
    await assetsPage.waitForAssetListed(assetId);
    await captureStep(page, "02-edc-provider-contract-definition-asset-created");

    await policiesPage.goto(dataspaceRuntime.provider.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC provider contract definition policy");
    await policiesPage.expectReady();
    await policiesPage.createSetPolicy(policyId);
    await policiesPage.waitForPolicyListed(policyId);
    await captureStep(page, "03-edc-provider-contract-definition-policy-created");

    await contractDefinitionsPage.goto(dataspaceRuntime.provider.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC provider contract definitions");
    await contractDefinitionsPage.expectReady();
    report.assetSelectionMode = await contractDefinitionsPage.createForAllAssets(contractDefinitionId, policyId);
    await contractDefinitionsPage.waitForContractDefinitionListed(contractDefinitionId, {
      policyId,
    });
    await captureStep(page, "04-edc-provider-contract-definition-created");

    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during provider contract definition creation: ${JSON.stringify(
        report.errorResponses,
      )}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-provider-contract-definition-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
