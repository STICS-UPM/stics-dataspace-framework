import { defineConfig } from "@playwright/test";
import dotenv from "dotenv";
import path from "path";

dotenv.config({ path: ".env" });

const outputDir = process.env.PLAYWRIGHT_OPS_OUTPUT_DIR || "ops-test-results";
const htmlReportDir = process.env.PLAYWRIGHT_OPS_HTML_REPORT_DIR || "ops-playwright-report";
const blobReportDir = process.env.PLAYWRIGHT_OPS_BLOB_REPORT_DIR || "ops-blob-report";
const jsonReportFile =
  process.env.PLAYWRIGHT_OPS_JSON_REPORT_FILE || path.join(outputDir, "results.json");

export default defineConfig({
  testDir: ".",
  testMatch: ["ops/**/*.spec.ts"],
  timeout: 4 * 60 * 1000,
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
  },
});
