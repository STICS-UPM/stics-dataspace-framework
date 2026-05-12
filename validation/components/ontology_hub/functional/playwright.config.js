const path = require("path");

const { defineConfig } = require("../ui/playwright-runtime");
const { resolveOntologyHubTimeouts } = require("../ui/runtime");

const outputDir = process.env.PLAYWRIGHT_OUTPUT_DIR || "test-results";
const htmlReportDir = process.env.PLAYWRIGHT_HTML_REPORT_DIR || "playwright-report";
const blobReportDir = process.env.PLAYWRIGHT_BLOB_REPORT_DIR || "blob-report";
const jsonReportFile =
  process.env.PLAYWRIGHT_JSON_REPORT_FILE || path.join(outputDir, "results.json");
const configuredWorkers = Number.parseInt(
  process.env.ONTOLOGY_HUB_UI_WORKERS || process.env.PLAYWRIGHT_WORKERS || "1",
  10,
);
const workers = Number.isFinite(configuredWorkers) && configuredWorkers > 0 ? configuredWorkers : 1;
const configuredValidationTimeoutMs = Number.parseInt(
  process.env.ONTOLOGY_HUB_UI_TIMEOUT_MS || "120000",
  10,
);
const headedGpuFix = process.env.PLAYWRIGHT_HEADED_GPU_FIX === "1";
const validationTimeoutMs =
  Number.isFinite(configuredValidationTimeoutMs) && configuredValidationTimeoutMs > 0
    ? configuredValidationTimeoutMs
    : 120000;
const timeouts = resolveOntologyHubTimeouts();

module.exports = defineConfig({
  testDir: path.join(__dirname, "specs"),
  testMatch: "**/*.spec.js",
  timeout: validationTimeoutMs,
  expect: {
    timeout: timeouts.expectTimeoutMs,
  },
  workers,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: htmlReportDir }],
    ["blob", { outputDir: blobReportDir }],
    ["json", { outputFile: jsonReportFile }],
  ],
  outputDir,
  retries: 0,
  use: {
    trace: "on",
    screenshot: "only-on-failure",
    video: "on",
    ignoreHTTPSErrors: true,
    actionTimeout: timeouts.actionTimeoutMs,
    navigationTimeout: timeouts.navigationTimeoutMs,
    launchOptions: headedGpuFix
      ? {
          args: ["--disable-gpu"],
        }
      : undefined,
  },
});
