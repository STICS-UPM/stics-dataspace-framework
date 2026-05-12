const { test, expect } = require("../../ui/fixtures");
const { gotoEdition } = require("../../ui/support/bootstrap");

test("OH-LOGIN: admin can sign in and reach the edition area", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  await gotoEdition(page, ontologyHubRuntime);
  await expect(page).toHaveURL(/\/edition(?:\/lov)?\/?$/);
  await page.locator(".createVocab").waitFor({ state: "visible" });
  await captureStep(page, "01-edition-login");

  await attachJson("oh-login-report", {
    user: ontologyHubRuntime.adminEmail,
    url: page.url(),
  });
});
