const path = require("path");

const { defineConfig } = require("./playwright-runtime");
const { resolveSemanticVirtualizationRuntime } = require("./runtime");

// When SEMANTIC_VIRTUALIZATION_INGRESS_RESOLVE_IP is set, route the SV public
// hostnames straight to the internal ingress IP in the browser. This bypasses
// an external reverse proxy that does not tunnel Streamlit WebSocket upgrades,
// while preserving the original Host header for ingress vhost routing.
function ingressHostResolverArgs() {
  try {
    const runtime = resolveSemanticVirtualizationRuntime();
    const ip = String(runtime.ingressResolveIp || "").trim();
    if (!ip) {
      return [];
    }
    const hosts = new Set();
    for (const candidate of [runtime.baseUrl, runtime.mappingEditorBaseUrl]) {
      try {
        const host = new URL(candidate).hostname;
        if (host) {
          hosts.add(host);
        }
      } catch (error) {
        // Ignore unparsable URLs.
      }
    }
    if (!hosts.size) {
      return [];
    }
    const rules = [...hosts].map((host) => `MAP ${host} ${ip}`).join(",");
    return [`--host-resolver-rules=${rules}`];
  } catch (error) {
    return [];
  }
}

const outputDir = process.env.PLAYWRIGHT_OUTPUT_DIR || "test-results";
const htmlReportDir = process.env.PLAYWRIGHT_HTML_REPORT_DIR || "playwright-report";
const blobReportDir = process.env.PLAYWRIGHT_BLOB_REPORT_DIR || "blob-report";
const jsonReportFile =
  process.env.PLAYWRIGHT_JSON_REPORT_FILE || path.join(outputDir, "results.json");
const consoleReporter = path.join(
  __dirname,
  "../../../ui/reporters/console-test-name-reporter.cjs",
);
const headedGpuFix = process.env.PLAYWRIGHT_HEADED_GPU_FIX === "1";

module.exports = defineConfig({
  testDir: "./specs",
  timeout: 2 * 60 * 1000,
  expect: {
    timeout: 20 * 1000,
  },
  workers: 1,
  reporter: [
    [consoleReporter],
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
    launchOptions: {
      args: [
        "--ignore-certificate-errors",
        "--disable-web-security",
        ...ingressHostResolverArgs(),
        ...(headedGpuFix ? ["--disable-gpu"] : []),
      ],
    },
  },
});
