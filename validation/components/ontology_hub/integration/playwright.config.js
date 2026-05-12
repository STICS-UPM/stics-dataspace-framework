const path = require("path");

const { defineConfig } = require("../ui/playwright-runtime");

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
const configuredBootstrapTimeoutMs = Number.parseInt(
  process.env.ONTOLOGY_HUB_BOOTSTRAP_TIMEOUT_MS || "120000",
  10,
);
const headedGpuFix = process.env.PLAYWRIGHT_HEADED_GPU_FIX === "1";
const validationTimeoutMs =
  Number.isFinite(configuredValidationTimeoutMs) && configuredValidationTimeoutMs > 0
    ? configuredValidationTimeoutMs
    : 120000;
const bootstrapTimeoutMs =
  Number.isFinite(configuredBootstrapTimeoutMs) && configuredBootstrapTimeoutMs > 0
    ? configuredBootstrapTimeoutMs
    : Math.max(validationTimeoutMs, 120000);
const bootstrapSpecPatterns = [
  /oh_login\.spec\.js$/,
  /pt5_oh_01_create_vocab\.spec\.js$/,
  /pt5_oh_02_edit_vocab\.spec\.js$/,
];

module.exports = defineConfig({
  testDir: path.join(__dirname, "specs"),
  timeout: validationTimeoutMs,
  expect: {
    timeout: 5000,
  },
  workers,
  projects: [
    {
      name: "bootstrap",
      testMatch: bootstrapSpecPatterns,
      workers: 1,
      timeout: bootstrapTimeoutMs,
    },
    {
      name: "validation",
      dependencies: ["bootstrap"],
      testIgnore: bootstrapSpecPatterns,
      workers,
      timeout: validationTimeoutMs,
    },
  ],
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
    actionTimeout: 5000,
    navigationTimeout: 5000,
    launchOptions: headedGpuFix
      ? {
          args: ["--disable-gpu"],
        }
      : undefined,
  },
});
