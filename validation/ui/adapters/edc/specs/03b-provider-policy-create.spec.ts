import { KeycloakLoginPage } from "../../../components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { EdcDashboardPage } from "../components/edc-dashboard.page";
import { EdcPoliciesPage } from "../components/edc-policies.page";

type ProviderPolicyReport = {
  startedAt: string;
  providerConnector: string;
  policyId: string;
  errorResponses: Array<{ url: string; status: number }>;
};

test("03b edc provider setup: policy creation from the UI", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const policyId = `qa-edc-policy-${suffix}`;
  const report: ProviderPolicyReport = {
    startedAt: new Date().toISOString(),
    providerConnector: dataspaceRuntime.provider.connectorName,
    policyId,
    errorResponses: [],
  };

  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);
  const policiesPage = new EdcPoliciesPage(page);

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
    await captureStep(page, "01-edc-provider-policy-after-login");

    await policiesPage.goto(dataspaceRuntime.provider.portalBaseUrl);
    await dashboardPage.expectNoServerErrorBanner("EDC provider policies");
    await policiesPage.expectReady();
    await policiesPage.createSetPolicy(policyId);
    await policiesPage.waitForPolicyListed(policyId);
    await captureStep(page, "02-edc-provider-policy-created");

    expect(
      report.errorResponses,
      `EDC dashboard proxy returned errors during provider policy creation: ${JSON.stringify(report.errorResponses)}`,
    ).toHaveLength(0);
  } finally {
    await attachJson("edc-provider-policy-report", {
      ...report,
      finishedAt: new Date().toISOString(),
    });
  }
});
