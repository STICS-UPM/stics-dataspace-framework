import { test, expect } from "../shared/fixtures/dataspace.fixture";
import { KeycloakLoginPage } from "../components/auth/keycloak-login.page";
import { ConnectorShellPage } from "../components/shell/connector-shell.page";
import { PolicyCreatePage } from "../components/provider/policy-create.page";

type ProviderPolicyReport = {
  startedAt: string;
  baseUrl: string;
  policyId: string;
  participantId: string;
  creationMessage?: string;
};

test("03b provider setup: policy creation from the UI", async ({
  page,
  dataspaceRuntime,
  captureStep,
  attachJson,
}) => {
  const suffix = `${Date.now()}`;
  const portalBaseUrl = dataspaceRuntime.provider.portalBaseUrl;
  const policyId = `qa-ui-policy-${suffix}`;
  const participantId = `participant-${suffix}`;
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
    skipLogin: false,
  });
  const shellPage = new ConnectorShellPage(page);
  const policyCreatePage = new PolicyCreatePage(page);
  const report: ProviderPolicyReport = {
    startedAt: new Date().toISOString(),
    baseUrl: portalBaseUrl,
    policyId,
    participantId,
  };

  try {
    await loginPage.open(portalBaseUrl);
    await loginPage.loginIfNeeded();
    await shellPage.expectReady();
    await captureStep(page, "01-policy-after-login");

    await policyCreatePage.goto(portalBaseUrl);
    await policyCreatePage.expectReady();
    await policyCreatePage.fillPolicyId(policyId);
    await policyCreatePage.addParticipantIdConstraint(participantId);
    await captureStep(page, "02-policy-form-complete");

    await policyCreatePage.submit();
    report.creationMessage = await policyCreatePage.waitForCreationSuccess();
    await policyCreatePage.expectPolicyListed(policyId);
    await captureStep(page, "03-policy-created");

    expect(report.creationMessage, "No policy creation notification was detected").toBeTruthy();
  } finally {
    await attachJson("provider-policy-report", report);
  }
});
