const { expect } = require("../fixtures");
const { clickMarked } = require("../support/live-marker");

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function gotoDashboardRoute(page, runtime, routePath, menuLabel, activeConnectorName = "") {
  await page.goto(`${runtime.baseUrl}${runtime.homePath || "/home"}`);
  await selectActiveConnector(page, activeConnectorName);

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

function cssAttributeValue(value) {
  return String(value || "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

async function selectActiveConnector(page, connectorName) {
  const normalizedName = String(connectorName || "").trim();
  if (!normalizedName) {
    return;
  }

  const radio = page
    .locator(`input[name="edc-config-dropdown"][aria-label="${cssAttributeValue(normalizedName)}"]`)
    .first();
  await expect(radio).toHaveCount(1);
  if (!(await radio.isChecked().catch(() => false))) {
    const visibleButton = page.getByRole("button", { name: normalizedName, exact: true }).first();
    if (await visibleButton.isVisible().catch(() => false)) {
      await clickMarked(visibleButton);
    } else {
      await radio.evaluate((element) => {
        element.checked = true;
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
      });
    }
  }
  await expect(radio).toBeChecked({ timeout: 10000 });
  await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => undefined);
}

module.exports = {
  gotoDashboardRoute,
  selectActiveConnector,
};
