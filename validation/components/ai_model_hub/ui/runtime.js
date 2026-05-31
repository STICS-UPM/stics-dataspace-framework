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

function resolveAdapterName() {
  const adapter = (process.env.AI_MODEL_HUB_COMPONENT_ADAPTER || process.env.PIONERA_ADAPTER || "inesdata")
    .trim()
    .toLowerCase();
  return ["inesdata", "edc"].includes(adapter) ? adapter : "inesdata";
}

function connectorFullName(connector, dataspace) {
  const normalized = (connector || "").trim();
  if (!normalized) {
    return "";
  }
  if (normalized.startsWith("conn-")) {
    return normalized;
  }
  return `conn-${normalized}-${dataspace}`;
}

function appendUrlPath(baseUrl, pathValue) {
  const base = (baseUrl || "").trim().replace(/\/$/, "");
  if (!base) {
    return "";
  }
  const pathPart = (pathValue || "").trim();
  if (!pathPart) {
    return base;
  }
  return `${base}${pathPart.startsWith("/") ? pathPart : `/${pathPart}`}`.replace(/\/$/, "");
}

function resolveAIModelHubRuntime() {
  const adapterName = resolveAdapterName();
  const deployerConfig = parseKeyValueFile(
    path.join(projectRoot(), "deployers", adapterName, "deployer.config"),
  );
  const deployerExampleConfig = parseKeyValueFile(
    path.join(projectRoot(), "deployers", adapterName, "deployer.config.example"),
  );
  const adapterConfig = { ...deployerExampleConfig, ...deployerConfig };
  const infrastructureConfig = parseKeyValueFile(
    path.join(projectRoot(), "deployers", "infrastructure", "deployer.config"),
  );
  const dataspace = (process.env.UI_DATASPACE || adapterConfig.DS_1_NAME || "demo").trim();
  const dsDomain = (
    process.env.UI_DS_DOMAIN ||
    adapterConfig.DS_DOMAIN_BASE ||
    infrastructureConfig.DS_DOMAIN_BASE ||
    "dev.ds.dataspaceunit.upm"
  ).trim();
  const componentsNamespace = (
    process.env.AI_MODEL_HUB_MODEL_SERVER_NAMESPACE ||
    process.env.UI_COMPONENTS_NAMESPACE ||
    adapterConfig.COMPONENTS_NAMESPACE ||
    "components"
  ).trim();
  const configuredModelServerBaseUrl = (
    process.env.AI_MODEL_HUB_MODEL_SERVER_BASE_URL ||
    adapterConfig.AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL ||
    adapterConfig.MODEL_SERVER_PUBLIC_URL ||
    appendUrlPath(
      adapterConfig.AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL || adapterConfig.COMPONENTS_PUBLIC_BASE_URL,
      adapterConfig.AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH || adapterConfig.MODEL_SERVER_PUBLIC_PATH || "/model-server",
    )
  ).trim();
  const keycloakBaseUrl = (
    process.env.AI_MODEL_HUB_KEYCLOAK_URL ||
    adapterConfig.KC_INTERNAL_URL ||
    infrastructureConfig.KC_INTERNAL_URL ||
    adapterConfig.KC_URL ||
    infrastructureConfig.KC_URL ||
    "http://keycloak.dev.ed.dataspaceunit.upm"
  )
    .trim()
    .replace(/\/$/, "");
  const configuredConnectors = (adapterConfig.DS_1_CONNECTORS || "")
    .split(",")
    .map(value => value.trim())
    .filter(Boolean);
  const defaultProvider = adapterName === "edc" ? "citycounciledc" : "citycouncil";
  const defaultConsumer = adapterName === "edc" ? "companyedc" : "company";
  const providerConnectorId = (
    process.env.AI_MODEL_HUB_PROVIDER_CONNECTOR_ID ||
    connectorFullName(configuredConnectors[0] || defaultProvider, dataspace)
  ).trim();
  const consumerConnectorId = (
    process.env.AI_MODEL_HUB_CONSUMER_CONNECTOR_ID ||
    connectorFullName(configuredConnectors[1] || defaultConsumer, dataspace)
  ).trim();

  return {
    adapterName,
    dataspace,
    dsDomain,
    componentsNamespace,
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
    providerConnectorId,
    providerManagementUrl:
      process.env.AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL ||
      `http://${providerConnectorId}.${dsDomain}/management`,
    providerProtocolUrl:
      process.env.AI_MODEL_HUB_PROVIDER_PROTOCOL_URL ||
      `http://${providerConnectorId}.${dsDomain}/protocol`,
    consumerConnectorName: process.env.AI_MODEL_HUB_CONSUMER_CONNECTOR_NAME || "Consumer",
    consumerConnectorId,
    consumerManagementUrl:
      process.env.AI_MODEL_HUB_CONSUMER_MANAGEMENT_URL ||
      `http://${consumerConnectorId}.${dsDomain}/management`,
    consumerProtocolUrl:
      process.env.AI_MODEL_HUB_CONSUMER_PROTOCOL_URL ||
      `http://${consumerConnectorId}.${dsDomain}/protocol`,
    providerDefaultUrl:
      process.env.AI_MODEL_HUB_PROVIDER_DEFAULT_URL ||
      `http://${providerConnectorId}.${dsDomain}/api`,
    consumerDefaultUrl:
      process.env.AI_MODEL_HUB_CONSUMER_DEFAULT_URL ||
      `http://${consumerConnectorId}.${dsDomain}/api`,
    modelServerBaseUrl: (
      configuredModelServerBaseUrl ||
      `http://model-server.${componentsNamespace}.svc.cluster.local:8080`
    ).replace(/\/$/, ""),
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
