import { defineConfig } from "@playwright/test";
import dotenv from "dotenv";
import path from "path";

dotenv.config({ path: ".env" });

const outputDir = process.env.PLAYWRIGHT_OUTPUT_DIR || "test-results";
const htmlReportDir = process.env.PLAYWRIGHT_HTML_REPORT_DIR || "playwright-report";
const blobReportDir = process.env.PLAYWRIGHT_BLOB_REPORT_DIR || "blob-report";
const jsonReportFile =
  process.env.PLAYWRIGHT_JSON_REPORT_FILE || path.join(outputDir, "results.json");
const headedGpuFix = process.env.PLAYWRIGHT_HEADED_GPU_FIX === "1";

export default defineConfig({
  testDir: ".",
  testMatch: ["adapters/edc/specs/**/*.spec.ts"],
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
    baseURL: process.env.PORTAL_BASE_URL,
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
