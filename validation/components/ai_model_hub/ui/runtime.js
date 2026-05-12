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

function resolveAIModelHubRuntime() {
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
  const keycloakBaseUrl = (
    process.env.AI_MODEL_HUB_KEYCLOAK_URL ||
    deployerConfig.KC_INTERNAL_URL ||
    infrastructureConfig.KC_INTERNAL_URL ||
    deployerConfig.KC_URL ||
    infrastructureConfig.KC_URL ||
    "http://keycloak.dev.ed.dataspaceunit.upm"
  )
    .trim()
    .replace(/\/$/, "");

  return {
    dataspace,
    dsDomain,
    keycloakBaseUrl,
    baseUrl:
      (process.env.AI_MODEL_HUB_BASE_URL || `http://ai-model-hub-${dataspace}.${dsDomain}`).replace(
        /\/$/,
        "",
      ),
    expectedAppTitle: process.env.AI_MODEL_HUB_EXPECTED_APP_TITLE || "EDC Dashboard",
    homePath: process.env.AI_MODEL_HUB_HOME_PATH || "/home",
    catalogPath: process.env.AI_MODEL_HUB_CATALOG_PATH || "/catalog",
    assetsPath: process.env.AI_MODEL_HUB_ASSETS_PATH || "/assets",
    mlAssetsPath: process.env.AI_MODEL_HUB_ML_ASSETS_PATH || "/ml-assets",
    modelExecutionPath: process.env.AI_MODEL_HUB_MODEL_EXECUTION_PATH || "/model-execution",
    modelBenchmarkingPath: process.env.AI_MODEL_HUB_MODEL_BENCHMARKING_PATH || "/model-benchmarking",
    contractsPath: process.env.AI_MODEL_HUB_CONTRACTS_PATH || "/contracts",
    searchTerm: process.env.AI_MODEL_HUB_SEARCH_TERM || "model",
    requestButtonLabel: process.env.AI_MODEL_HUB_REQUEST_BUTTON_LABEL || "Request Manually",
    providerConnectorName: process.env.AI_MODEL_HUB_PROVIDER_CONNECTOR_NAME || "Provider",
    providerConnectorId: process.env.AI_MODEL_HUB_PROVIDER_CONNECTOR_ID || `conn-citycouncil-${dataspace}`,
    providerManagementUrl:
      process.env.AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL ||
      `http://conn-citycouncil-${dataspace}.${dsDomain}/management`,
    providerProtocolUrl:
      process.env.AI_MODEL_HUB_PROVIDER_PROTOCOL_URL ||
      `http://conn-citycouncil-${dataspace}.${dsDomain}/protocol`,
    consumerConnectorName: process.env.AI_MODEL_HUB_CONSUMER_CONNECTOR_NAME || "Consumer",
    consumerConnectorId: process.env.AI_MODEL_HUB_CONSUMER_CONNECTOR_ID || `conn-company-${dataspace}`,
    consumerManagementUrl:
      process.env.AI_MODEL_HUB_CONSUMER_MANAGEMENT_URL ||
      `http://conn-company-${dataspace}.${dsDomain}/management`,
    providerDefaultUrl:
      process.env.AI_MODEL_HUB_PROVIDER_DEFAULT_URL ||
      `http://conn-citycouncil-${dataspace}.${dsDomain}/api`,
    consumerDefaultUrl:
      process.env.AI_MODEL_HUB_CONSUMER_DEFAULT_URL ||
      `http://conn-company-${dataspace}.${dsDomain}/api`,
    modelContentType: process.env.AI_MODEL_HUB_MODEL_CONTENT_TYPE || "application/json",
    modelVersion: process.env.AI_MODEL_HUB_MODEL_VERSION || "v1.0.0",
    modelDescription:
      process.env.AI_MODEL_HUB_MODEL_DESCRIPTION ||
      "PT5-MH-02 local registration smoke model created by Playwright.",
  };
}

module.exports = {
  resolveAIModelHubRuntime,
};
