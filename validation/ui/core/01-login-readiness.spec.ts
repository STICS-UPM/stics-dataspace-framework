import { test, expect } from "../shared/fixtures/auth.fixture";

test("01 login readiness: authentication and shell loaded", async ({
  page,
  ensureLoggedIn,
  shellPage,
  captureStep,
}) => {
  await ensureLoggedIn();
  await captureStep(page, "01-after-login");

  await shellPage.expectReady();
  await shellPage.assertNoGateway403("Portal shell");
  await shellPage.assertNoServerErrorBanner("Portal shell");

  expect(
    await page.locator("text=Log out").count(),
    "Login did not succeed: 'Log out' button not found",
  ).toBeGreaterThan(0);
});
