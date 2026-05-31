const fs = require("fs");
const path = require("path");

function projectRoot() {
  return path.resolve(__dirname, "../../../..");
}

function parseKeyValueFile(filePath) {
  if (!fs.existsSync(filePath)) {
    return {};
  }
  const values = {};
  const content = fs.readFileSync(filePath, "utf8");
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

function trimTrailingSlash(value) {
  return String(value || "").trim().replace(/\/$/, "");
}

function joinUrl(baseUrl, relativePath) {
  const normalizedBase = `${trimTrailingSlash(baseUrl)}/`;
  const rawPath = String(relativePath || "/");
  const normalizedPath = rawPath.replace(/^\//, "");
  const url = new URL(normalizedPath, normalizedBase).toString();
  return rawPath.trim() === "/" ? url : url.replace(/\/$/, "");
}

function resolveSemanticVirtualizationRuntime() {
  const deployerConfig = parseKeyValueFile(
    path.join(projectRoot(), "deployers", "inesdata", "deployer.config"),
  );
  const infrastructureConfig = parseKeyValueFile(
    path.join(projectRoot(), "deployers", "infrastructure", "deployer.config"),
  );
  const dataspace = (process.env.UI_DATASPACE || deployerConfig.DS_1_NAME || "demo").trim();
  const dsDomain = (
    process.env.UI_DS_DOMAIN ||
    deployerConfig.DS_DOMAIN_BASE ||
    infrastructureConfig.DS_DOMAIN_BASE ||
    "dev.ds.dataspaceunit.upm"
  ).trim();
  const baseUrl = trimTrailingSlash(
    process.env.SEMANTIC_VIRTUALIZATION_BASE_URL ||
      process.env.SEMANTIC_VIRTUALIZATION_PUBLIC_URL ||
      `http://semantic-virtualization-${dataspace}.${dsDomain}`,
  );
  const mappingEditorBaseUrl = trimTrailingSlash(
    process.env.SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_BASE_URL ||
      process.env.SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL ||
      process.env.MAPPING_EDITOR_BASE_URL ||
      `http://semantic-virtualization-editor-${dataspace}.${dsDomain}`,
  );

  return {
    dataspace,
    dsDomain,
    baseUrl,
    mappingEditorBaseUrl,
    rootPath: process.env.SEMANTIC_VIRTUALIZATION_ROOT_PATH || "/",
    mappingEditorRootPath: process.env.SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ROOT_PATH || "/",
    capabilitiesPath: process.env.SEMANTIC_VIRTUALIZATION_CAPABILITIES_PATH || "/openapi.json",
    queryPath:
      process.env.SEMANTIC_VIRTUALIZATION_QUERY_PATH ||
      "/?query=SELECT%20*%20WHERE%20%7B%20%3Fs%20%3Fp%20%3Fo%20.%20%7D%20LIMIT%201",
  };
}

module.exports = {
  joinUrl,
  resolveSemanticVirtualizationRuntime,
};
