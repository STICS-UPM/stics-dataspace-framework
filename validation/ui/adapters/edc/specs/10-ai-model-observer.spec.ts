import { KeycloakLoginPage } from "../../../shared/components/auth/keycloak-login.page";
import { test, expect } from "../../../shared/fixtures/dataspace.fixture";
import { EdcDashboardPage } from "../components/edc-dashboard.page";

test.skip(
  process.env.UI_EDC_MODEL_OBSERVER_DEMO !== "1",
  "Set UI_EDC_MODEL_OBSERVER_DEMO=1 to require AI Model Observer UI parity in the EDC dashboard.",
);

test("10 edc AI Model Observer: dashboard route is available for model evidence", async ({
  page,
  dataspaceRuntime,
  captureStep,
}) => {
  const loginPage = new KeycloakLoginPage(page, {
    portalUser: dataspaceRuntime.provider.username,
    portalPassword: dataspaceRuntime.provider.password,
    skipLogin: false,
  });
  const dashboardPage = new EdcDashboardPage(page);

  await loginPage.open(dataspaceRuntime.provider.portalBaseUrl);
  await loginPage.loginIfNeeded();
  await dashboardPage.expectShellReady();

  const observerNavCount = await page.locator("a, button").filter({ hasText: /AI Model Observer/i }).count();
  expect(
    observerNavCount,
    "EDC dashboard does not currently expose an AI Model Observer route. This is a real UI parity gap, not a framework skip.",
  ).toBeGreaterThan(0);

  await dashboardPage.navigateToSection("AI Model Observer", "/edc-dashboard/ai-model-observer");
  await dashboardPage.expectNoServerErrorBanner("EDC AI Model Observer");
  await expect(page.getByText(/AI Model Observer/i).first()).toBeVisible({ timeout: 30_000 });
  await captureStep(page, "01-edc-ai-model-observer");
});
