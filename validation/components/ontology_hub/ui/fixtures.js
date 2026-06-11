const fs = require("fs");

const { test: base, expect } = require("./playwright-runtime");
const { resolveOntologyHubRuntime, resolveOntologyHubTimeouts } = require("./runtime");
const { ensureOntologyHubBootstrap, installOptionalThirdPartyResourceGuards } = require("./support/bootstrap");
const timeouts = resolveOntologyHubTimeouts();

async function attachCaptureWarning(testInfo, name, error) {
  const outputPath = testInfo.outputPath(`${name}-capture-warning.txt`);
  const message = error && (error.stack || error.message) ? error.stack || error.message : String(error);
  fs.writeFileSync(outputPath, message, "utf8");
  await testInfo.attach(`${name}-capture-warning`, {
    path: outputPath,
    contentType: "text/plain",
  });
}

const test = base.extend({
  page: async ({ page }, use) => {
    page.setDefaultTimeout(timeouts.readyTimeoutMs);
    page.setDefaultNavigationTimeout(timeouts.navigationTimeoutMs);
    await installOptionalThirdPartyResourceGuards(page);
    await use(page);
  },

  ontologyHubRuntime: async ({}, use) => {
    await use(resolveOntologyHubRuntime());
  },

  ontologyHubBootstrap: async ({ page, ontologyHubRuntime }, use) => {
    await use(await ensureOntologyHubBootstrap(page, ontologyHubRuntime));
  },

  captureStep: async ({}, use, testInfo) => {
    await use(async (page, name) => {
      const outputPath = testInfo.outputPath(`${name}.png`);
      try {
        await page.screenshot({
          path: outputPath,
          fullPage: true,
          animations: "disabled",
          timeout: 15000,
        });
        await testInfo.attach(name, {
          path: outputPath,
          contentType: "image/png",
        });
        return;
      } catch (error) {
        await attachCaptureWarning(testInfo, name, error);
      }

      const fallbackPath = testInfo.outputPath(`${name}-viewport.png`);
      try {
        await page.screenshot({
          path: fallbackPath,
          fullPage: false,
          animations: "disabled",
          timeout: 15000,
        });
        await testInfo.attach(name, {
          path: fallbackPath,
          contentType: "image/png",
        });
      } catch (error) {
        await attachCaptureWarning(testInfo, `${name}-viewport`, error);
      }
    });
  },

  attachJson: async ({}, use, testInfo) => {
    await use(async (name, payload) => {
      const outputPath = testInfo.outputPath(`${name}.json`);
      fs.writeFileSync(outputPath, JSON.stringify(payload, null, 2), "utf8");
      await testInfo.attach(name, {
        path: outputPath,
        contentType: "application/json",
      });
    });
  },
});

module.exports = {
  test,
  expect,
};
