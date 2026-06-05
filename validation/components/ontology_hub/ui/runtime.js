const fs = require("fs");
const path = require("path");

function projectRoot() {
  return path.resolve(__dirname, "../../../..");
}

function parseKeyValueFile(filePath) {
  if (!fs.existsSync(filePath)) {
    return {};
  }
  const content = fs.readFileSync(filePath, "utf8");
  const values = {};
  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    const separator = trimmed.indexOf("=");
    if (separator <= 0) {
      continue;
    }
    values[trimmed.slice(0, separator).trim()] = trimmed.slice(separator + 1).trim();
  }
  return values;
}

function parseJsonFile(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return null;
  }

  const payload = JSON.parse(fs.readFileSync(filePath, "utf8"));
  return payload && typeof payload === "object" && !Array.isArray(payload) ? payload : null;
}

function readSecretFile(filePath) {
  const candidate = String(filePath || "").trim();
  if (!candidate || !fs.existsSync(candidate)) {
    return "";
  }

  return fs.readFileSync(candidate, "utf8").trim();
}

function normalizePositiveInteger(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function normalizeRepositoryUri(value) {
  const candidate = String(value || "").trim();
  if (!candidate) {
    return "";
  }

  try {
    const parsed = new URL(candidate);
    let pathname = parsed.pathname.replace(/\/+$/, "");
    if (
      ["github.com", "www.github.com", "gitlab.com", "www.gitlab.com"].includes(
        parsed.hostname.toLowerCase(),
      ) &&
      pathname.toLowerCase().endsWith(".git")
    ) {
      pathname = pathname.slice(0, -4);
    }
    parsed.pathname = pathname;
    return parsed.toString().replace(/\/$/, "");
  } catch (error) {
    return candidate.replace(/\/$/, "");
  }
}

function normalizeRuntime(runtime) {
  return {
    ...runtime,
    baseUrl: String(runtime.baseUrl || "").replace(/\/$/, ""),
    creationRepositoryUri: normalizeRepositoryUri(runtime.creationRepositoryUri),
    uiWorkers: normalizePositiveInteger(runtime.uiWorkers, 1),
    uiExpectTimeoutMs: normalizePositiveInteger(runtime.uiExpectTimeoutMs, 15000),
    uiActionTimeoutMs: normalizePositiveInteger(runtime.uiActionTimeoutMs, 15000),
    uiNavigationTimeoutMs: normalizePositiveInteger(runtime.uiNavigationTimeoutMs, 30000),
    uiReadyTimeoutMs: normalizePositiveInteger(runtime.uiReadyTimeoutMs, 30000),
    preflightTimeout: normalizePositiveInteger(runtime.preflightTimeout, 180),
    versionTimeoutMs: normalizePositiveInteger(runtime.versionTimeoutMs, 240000),
    strictPreflight: Boolean(runtime.strictPreflight),
  };
}

function buildOntologyHubUrl(baseUrl, appPath = "") {
  const base = String(baseUrl || "").trim().replace(/\/+$/, "");
  if (!base) {
    return String(appPath || "");
  }
  const suffix = String(appPath || "").trim().replace(/^\/+/, "");
  return suffix ? `${base}/${suffix}` : base;
}

function resolveOntologyHubRedirectUrl(baseUrl, targetPath = "") {
  const target = String(targetPath || "").trim();
  if (!target) {
    return buildOntologyHubUrl(baseUrl);
  }
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(target)) {
    try {
      const base = new URL(buildOntologyHubUrl(baseUrl));
      const parsedTarget = new URL(target);
      const basePath = base.pathname.replace(/\/+$/, "");
      const targetPathname = parsedTarget.pathname || "/";
      if (
        base.origin === parsedTarget.origin &&
        basePath &&
        basePath !== "/" &&
        !targetPathname.startsWith(`${basePath}/`) &&
        targetPathname !== basePath
      ) {
        parsedTarget.pathname = `${basePath}${targetPathname.startsWith("/") ? "" : "/"}${targetPathname}`;
        return parsedTarget.toString();
      }
    } catch (error) {
      return target;
    }
    return target;
  }
  return buildOntologyHubUrl(baseUrl, target);
}

function inferOntologyHubBaseUrl(currentUrl) {
  try {
    const parsed = new URL(String(currentUrl || ""));
    const pathname = parsed.pathname.replace(/\/+$/, "");
    const marker = pathname.match(/^(.*?)(?:\/(?:dataset|edition)(?:\/|$).*)$/);
    parsed.pathname = marker ? marker[1] || "/" : pathname || "/";
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString().replace(/\/+$/, "");
  } catch (error) {
    return "";
  }
}

function resolveRuntimeValue(envName, deployerConfig, fallback, options = {}) {
  const directEnv = String(process.env[envName] || "").trim();
  if (directEnv) {
    return directEnv;
  }

  const envFileValue = readSecretFile(process.env[`${envName}_FILE`]);
  if (envFileValue) {
    return envFileValue;
  }

  if (options.allowConfigFallback === false) {
    return fallback;
  }

  const directConfig = String(deployerConfig[envName] || "").trim();
  if (directConfig) {
    return directConfig;
  }

  const configFileValue = readSecretFile(deployerConfig[`${envName}_FILE`]);
  if (configFileValue) {
    return configFileValue;
  }

  return fallback;
}

function resolveOntologyHubRuntime() {
  const deployerConfig = parseKeyValueFile(
    path.join(projectRoot(), "deployers", "inesdata", "deployer.config"),
  );
  const dataspace = (process.env.UI_DATASPACE || deployerConfig.DS_1_NAME || "demo").trim();
  const dsDomain = (process.env.UI_DS_DOMAIN || deployerConfig.DS_DOMAIN_BASE || "dev.ds.dataspaceunit.upm").trim();
  const runtimeFile = process.env.ONTOLOGY_HUB_RUNTIME_FILE;
  const fileRuntime = parseJsonFile(runtimeFile);

  const fallbackRuntime = {
    dataspace,
    dsDomain,
    baseUrl:
      (process.env.ONTOLOGY_HUB_BASE_URL || `http://ontology-hub-${dataspace}.${dsDomain}`).replace(
        /\/$/,
        "",
      ),
    adminEmail: resolveRuntimeValue("ONTOLOGY_HUB_ADMIN_EMAIL", deployerConfig, "admin@gmail.com", {
      allowConfigFallback: false,
    }),
    adminPassword: resolveRuntimeValue(
      "ONTOLOGY_HUB_ADMIN_PASSWORD",
      deployerConfig,
      "admin1234",
      {
        allowConfigFallback: false,
      },
    ),
    expectedVocabularyPrefix: process.env.ONTOLOGY_HUB_EXPECTED_VOCAB || "saref4grid",
    expectedVocabularyTitle: process.env.ONTOLOGY_HUB_EXPECTED_TITLE || "SAREF4GRID",
    expectedSearchTerm: process.env.ONTOLOGY_HUB_EXPECTED_QUERY || "Person",
    expectedLabel: process.env.ONTOLOGY_HUB_EXPECTED_LABEL || "Person",
    expectedClassUri: process.env.ONTOLOGY_HUB_EXPECTED_CLASS_URI || "http://schema.org/Person",
    expectedClassPrefixedName:
      process.env.ONTOLOGY_HUB_EXPECTED_CLASS_PREFIXED_NAME || "saref4grid:Person",
    expectedPrimaryTag: process.env.ONTOLOGY_HUB_EXPECTED_PRIMARY_TAG || "Services",
    expectedSecondaryTag: process.env.ONTOLOGY_HUB_EXPECTED_SECONDARY_TAG || "Environment",
    previousVersionDate: process.env.ONTOLOGY_HUB_PREVIOUS_VERSION_DATE || "2025-01-15",
    latestVersionDate: process.env.ONTOLOGY_HUB_LATEST_VERSION_DATE || "2026-03-22",
    creationUri:
      process.env.ONTOLOGY_HUB_CREATION_URI || "https://saref.etsi.org/saref4grid/v2.1.1/",
    versionCreationUri:
      process.env.ONTOLOGY_HUB_VERSION_CREATION_URI || "https://saref.etsi.org/saref4city/v1.1.2/",
    versionCreationNamespace:
      process.env.ONTOLOGY_HUB_VERSION_CREATION_NAMESPACE || "https://saref.etsi.org/saref4city/",
    creationRepositoryUri:
      process.env.ONTOLOGY_HUB_CREATION_REPOSITORY_URI ||
      "",
    creationNamespace:
      process.env.ONTOLOGY_HUB_CREATION_NAMESPACE || "https://saref.etsi.org/saref4grid/",
    creationPrefix: process.env.ONTOLOGY_HUB_CREATION_PREFIX || "saref4grid",
    creationTitle:
      process.env.ONTOLOGY_HUB_CREATION_TITLE || "SAREF4GRID Vocabulary",
    creationDescription:
      process.env.ONTOLOGY_HUB_CREATION_DESCRIPTION ||
      "Vocabulary created through the Ontology Hub Playwright validation flow.",
    creationPrimaryLanguage:
      process.env.ONTOLOGY_HUB_CREATION_PRIMARY_LANGUAGE || "en",
    creationSecondaryLanguage:
      process.env.ONTOLOGY_HUB_CREATION_SECONDARY_LANGUAGE || "es",
    creationTag: process.env.ONTOLOGY_HUB_CREATION_TAG || "Services",
    creationReview:
      process.env.ONTOLOGY_HUB_CREATION_REVIEW || "Validated through the Playwright ontology flow.",
    listingSearchTerm: process.env.ONTOLOGY_HUB_LISTING_QUERY || "saref4grid",
    uiWorkers: normalizePositiveInteger(process.env.ONTOLOGY_HUB_UI_WORKERS, 1),
    uiExpectTimeoutMs: normalizePositiveInteger(
      process.env.ONTOLOGY_HUB_UI_EXPECT_TIMEOUT_MS,
      15000,
    ),
    uiActionTimeoutMs: normalizePositiveInteger(
      process.env.ONTOLOGY_HUB_UI_ACTION_TIMEOUT_MS,
      15000,
    ),
    uiNavigationTimeoutMs: normalizePositiveInteger(
      process.env.ONTOLOGY_HUB_UI_NAVIGATION_TIMEOUT_MS,
      30000,
    ),
    uiReadyTimeoutMs: normalizePositiveInteger(
      process.env.ONTOLOGY_HUB_UI_READY_TIMEOUT_MS,
      30000,
    ),
    strictPreflight: ["1", "true", "yes", "on"].includes(
      String(process.env.ONTOLOGY_HUB_UI_STRICT_PREFLIGHT || "").toLowerCase(),
    ),
    preflightTimeout: normalizePositiveInteger(process.env.ONTOLOGY_HUB_UI_PREFLIGHT_TIMEOUT, 180),
    versionTimeoutMs: normalizePositiveInteger(
      process.env.ONTOLOGY_HUB_VERSION_TIMEOUT_MS,
      240000,
    ),
  };

  return normalizeRuntime(fileRuntime ? { ...fallbackRuntime, ...fileRuntime } : fallbackRuntime);
}

function resolveOntologyHubTimeouts() {
  const runtime = resolveOntologyHubRuntime();
  return {
    expectTimeoutMs: normalizePositiveInteger(runtime.uiExpectTimeoutMs, 15000),
    actionTimeoutMs: normalizePositiveInteger(runtime.uiActionTimeoutMs, 15000),
    navigationTimeoutMs: normalizePositiveInteger(runtime.uiNavigationTimeoutMs, 15000),
    readyTimeoutMs: normalizePositiveInteger(runtime.uiReadyTimeoutMs, 15000),
  };
}

module.exports = {
  buildOntologyHubUrl,
  inferOntologyHubBaseUrl,
  resolveOntologyHubRuntime,
  resolveOntologyHubRedirectUrl,
  resolveOntologyHubTimeouts,
};
