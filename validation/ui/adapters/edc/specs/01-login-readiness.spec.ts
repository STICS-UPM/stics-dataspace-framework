import { KeycloakLoginPage } from "../../../components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { EdcDashboardPage } from "../components/edc-dashboard.page";

test("01 edc login readiness: oidc-bff authentication and dashboard shell loaded", async ({
  page,
  dataspaceRuntime,
  captureStep,
}) => {
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.consumer.username,
    portalPassword: dataspaceRuntime.consumer.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);

  expect(dataspaceRuntime.adapter, "This suite is intended for the EDC adapter runtime").toBe("edc");

  await loginPage.open(dataspaceRuntime.consumer.portalBaseUrl);
  await loginPage.loginIfNeeded();
  await dashboardPage.expectShellReady();
  await dashboardPage.expectAuthenticatedSession();
  await dashboardPage.expectNoServerErrorBanner("EDC dashboard shell");
  await captureStep(page, "01-edc-after-login");
});
