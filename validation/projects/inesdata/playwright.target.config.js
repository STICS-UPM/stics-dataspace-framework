const path = require("path");
const Module = require("module");

const uiNodeModules = path.resolve(__dirname, "../../ui/node_modules");
process.env.NODE_PATH = [uiNodeModules, process.env.NODE_PATH].filter(Boolean).join(path.delimiter);
Module._initPaths();

const { defineConfig } = require("@playwright/test");

const outputDir = process.env.PLAYWRIGHT_OUTPUT_DIR || "test-results";
const htmlReportDir = process.env.PLAYWRIGHT_HTML_REPORT_DIR || "playwright-report";
const blobReportDir = process.env.PLAYWRIGHT_BLOB_REPORT_DIR || "blob-report";
const jsonReportFile =
  process.env.PLAYWRIGHT_JSON_REPORT_FILE || path.join(outputDir, "results.json");
const headedGpuFix = process.env.PLAYWRIGHT_HEADED_GPU_FIX === "1";

module.exports = defineConfig({
  testDir: __dirname,
  timeout: 2 * 60 * 1000,
  expect: {
    timeout: 15 * 1000,
  },
  retries: 0,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: htmlReportDir }],
    ["blob", { outputDir: blobReportDir }],
    ["json", { outputFile: jsonReportFile }],
  ],
  outputDir,
  use: {
    trace: "on",
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
