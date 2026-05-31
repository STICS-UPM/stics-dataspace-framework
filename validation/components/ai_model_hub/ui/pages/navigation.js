const { expect } = require("../fixtures");
const { clickMarked } = require("../support/live-marker");

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function gotoDashboardRoute(page, runtime, routePath, menuLabel) {
  await page.goto(`${runtime.baseUrl}${runtime.homePath || "/home"}`);

  const menuButton = page
    .locator("button")
    .filter({ has: page.getByText(menuLabel, { exact: true }) })
    .first();
  await expect(menuButton).toBeVisible({ timeout: 20000 });
  await clickMarked(menuButton);

  const expectedRoute = String(routePath || "").replace(/\/$/, "");
  if (expectedRoute) {
    await expect(page).toHaveURL(new RegExp(`${escapeRegExp(expectedRoute)}$`));
  }
}

module.exports = {
  gotoDashboardRoute,
};
