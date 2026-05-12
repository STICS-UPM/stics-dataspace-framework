const path = require("path");

const { defineConfig } = require("./playwright-runtime");

const outputDir = process.env.PLAYWRIGHT_OUTPUT_DIR || "test-results";
const htmlReportDir = process.env.PLAYWRIGHT_HTML_REPORT_DIR || "playwright-report";
const blobReportDir = process.env.PLAYWRIGHT_BLOB_REPORT_DIR || "blob-report";
const jsonReportFile =
  process.env.PLAYWRIGHT_JSON_REPORT_FILE || path.join(outputDir, "results.json");
const headedGpuFix = process.env.PLAYWRIGHT_HEADED_GPU_FIX === "1";

function resolveTraceMode() {
  const value = (process.env.PLAYWRIGHT_TRACE || "").trim().toLowerCase();
  if (["on", "off", "retain-on-failure", "on-first-retry", "on-all-retries"].includes(value)) {
    return value;
  }
  if (["1", "true", "yes"].includes(value)) {
    return "on";
  }
  return "off";
}

module.exports = defineConfig({
  testDir: "./specs",
  timeout: 2 * 60 * 1000,
  expect: {
    timeout: 20 * 1000,
  },
  workers: 1,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: htmlReportDir }],
    ["blob", { outputDir: blobReportDir }],
    ["json", { outputFile: jsonReportFile }],
  ],
  outputDir,
  retries: 0,
  use: {
    trace: resolveTraceMode(),
    screenshot: "only-on-failure",
    video: "on",
    ignoreHTTPSErrors: true,
    launchOptions: headedGpuFix
      ? {
          args: ["--disable-gpu"],
        }
      : undefined,
  },
});
