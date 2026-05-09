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
const hostResolverRules = (process.env.PLAYWRIGHT_HOST_RESOLVER_RULES || "").trim();
const semanticVirtualizationHttpDataDemo =
  process.env.UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO === "1";
const ontologyHubInesdataDemo = process.env.UI_ONTOLOGY_HUB_INESDATA_DEMO === "1";
const aiModelHubHttpDataDemo = process.env.UI_AI_MODEL_HUB_HTTPDATA_DEMO === "1";
const aiModelObserverDemo = process.env.UI_AI_MODEL_OBSERVER_DEMO === "1";
const launchArgs = [
  ...(headedGpuFix ? ["--disable-gpu"] : []),
  ...(hostResolverRules ? [`--host-resolver-rules=${hostResolverRules}`] : []),
];

type TraceMode = "on" | "off" | "retain-on-failure" | "on-first-retry" | "on-all-retries";

function resolveTraceMode(): TraceMode {
  const value = (process.env.PLAYWRIGHT_TRACE || "").trim().toLowerCase();
  if (["on", "off", "retain-on-failure", "on-first-retry", "on-all-retries"].includes(value)) {
    return value as TraceMode;
  }
  if (["0", "false", "no"].includes(value)) {
    return "off";
  }
  return "on";
}

export default defineConfig({
  testDir: ".",
  testMatch: ["core/**/*.spec.ts"],
  testIgnore: [
    ...(semanticVirtualizationHttpDataDemo ? [] : ["core/07-semantic-virtualization-httpdata.spec.ts"]),
    ...(ontologyHubInesdataDemo ? [] : ["core/08-ontology-hub-inesdata-readonly.spec.ts"]),
    ...(aiModelHubHttpDataDemo ? [] : ["core/09-ai-model-hub-httpdata.spec.ts"]),
    ...(aiModelObserverDemo ? [] : ["core/10-ai-model-observer.spec.ts"]),
  ],
  timeout: 4 * 60 * 1000,
  expect: {
    timeout: 15 * 1000,
  },
  retries: 0,
  // These UI flows share portal state and external services; keep them sequential by default.
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
    trace: resolveTraceMode(),
    screenshot: "only-on-failure",
    video: "on",
    ignoreHTTPSErrors: true,
    launchOptions: launchArgs.length > 0
      ? {
          args: launchArgs,
        }
      : undefined,
  },
});
