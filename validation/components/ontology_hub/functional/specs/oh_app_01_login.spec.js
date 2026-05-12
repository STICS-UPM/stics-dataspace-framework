// Excel traceability: Ontology Hub case 2 (Iniciar Sesion), adapted to the current UI.
const { test, expect } = require("../../ui/fixtures");
const { signInToEdition, signOut } = require("../support/excel-flows");

test("OH-APP-01: admin can sign in and sign out", async ({
  page,
  ontologyHubRuntime,
  captureStep,
  attachJson,
}) => {
  await signInToEdition(page, ontologyHubRuntime);
  await page.locator("a[href='/edition/'], a[href='/edition']").first().waitFor({ state: "visible" });
  await page.locator("a[href*='/edition/users/']").first().waitFor({ state: "visible" });
  await page.locator("a[href='/edition/logout']").first().waitFor({ state: "visible" });
  await captureStep(page, "01-edition-access");

  await signOut(page, ontologyHubRuntime);
  await expect(page.locator("body")).toContainText(/vocabs|terms|log in/i);
  await captureStep(page, "02-after-logout");

  await attachJson("oh-app-01-report", {
    user: ontologyHubRuntime.adminEmail,
    afterLogoutUrl: page.url(),
  });
});
