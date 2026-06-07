import fs from "fs";
import path from "path";

export type ConnectorPortalRuntime = {
  adapter: string;
  connectorName: string;
  portalBaseUrl: string;
  managementBaseUrl: string;
  protocolBaseUrl: string;
  transferStartPath: string;
  transferDestinationType: string;
  username: string;
  password: string;
  transferDestination?: {
    bucketName: string;
    region: string;
    endpointOverride: string;
    accessKeyId: string;
    secretAccessKey: string;
  };
};

export type DataspacePortalRuntime = {
  adapter: string;
  dataspace: string;
  componentsNamespace: string;
  dsDomain: string;
  keycloakUrl: string;
  keycloakClientId: string;
  provider: ConnectorPortalRuntime;
  consumer: ConnectorPortalRuntime;
};

type DataspaceDefaults = {
  adapter: string;
  dataspace: string;
  componentsNamespace: string;
  environment: string;
  dsDomain: string;
  keycloakUrl: string;
  keycloakClientId: string;
};

function projectRoot(): string {
  return path.resolve(__dirname, "../../../..");
}

function parseKeyValueFile(filePath: string): Record<string, string> {
  const content = fs.readFileSync(filePath, "utf8");
  const values: Record<string, string> = {};

  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }

    const separator = trimmed.indexOf("=");
    if (separator <= 0) {
      continue;
    }

    const key = trimmed.slice(0, separator).trim();
    const value = trimmed.slice(separator + 1).trim();
    values[key] = value;
  }

  return values;
}

function readJson(filePath: string): any {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readJsonIfExists(filePath: string): any | undefined {
  if (!fs.existsSync(filePath)) {
    return undefined;
  }
  return readJson(filePath);
}

function requiredString(value: string | undefined, label: string): string {
  if (!value || value.trim().length === 0) {
    throw new Error(`Missing value for ${label}`);
  }
  return value.trim();
}

function stringMap(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object") {
    return {};
  }

  const result: Record<string, string> = {};
  for (const [key, rawValue] of Object.entries(value as Record<string, unknown>)) {
    if (typeof rawValue === "string" && rawValue.trim().length > 0) {
      result[key] = rawValue.trim();
    }
  }
  return result;
}

function withoutTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function withTrailingSlash(value: string): string {
  return `${withoutTrailingSlash(value)}/`;
}

function optionalUrl(value: string | undefined): string | undefined {
  if (!value || value.trim().length === 0) {
    return undefined;
  }
  return withoutTrailingSlash(value.trim());
}

function optionalPortalUrl(value: string | undefined): string | undefined {
  if (!value || value.trim().length === 0) {
    return undefined;
  }
  return withTrailingSlash(value.trim());
}

function appendUrlPath(baseUrl: string | undefined, pathSuffix: string): string | undefined {
  const base = optionalUrl(baseUrl);
  if (!base) {
    return undefined;
  }
  const suffix = pathSuffix.startsWith("/") ? pathSuffix : `/${pathSuffix}`;
  return `${base}${suffix}`;
}

function normalizedAdapter(): string {
  const value = (process.env.UI_ADAPTER || "inesdata").trim().toLowerCase();
  return value || "inesdata";
}

function connectorEnvPrefix(connectorName: string): string {
  return connectorName.toUpperCase().replace(/-/g, "_");
}

function normalizeConnectorName(rawName: string | undefined, dataspace: string): string | undefined {
  const connector = rawName?.trim();
  if (!connector) {
    return undefined;
  }
  if (connector.startsWith("conn-")) {
    return connector;
  }
  return dataspace.trim() ? `conn-${connector}-${dataspace.trim()}` : connector;
}

function parseConnectorList(rawValue: string | undefined, dataspace: string): string[] {
  const connectors: string[] = [];
  for (const token of (rawValue || "").split(",")) {
    const connector = normalizeConnectorName(token, dataspace);
    if (connector && !connectors.includes(connector)) {
      connectors.push(connector);
    }
  }
  return connectors;
}

function parseConnectorPairs(rawValue: string | undefined, dataspace: string): Array<[string, string]> {
  const pairs: Array<[string, string]> = [];
  for (const token of (rawValue || "").split(",")) {
    const item = token.trim();
    if (!item) {
      continue;
    }

    let left = "";
    let right = "";
    for (const separator of ["->", ">", "="]) {
      if (item.includes(separator)) {
        [left, right] = item.split(separator, 2);
        break;
      }
    }

    const source = normalizeConnectorName(left, dataspace);
    const target = normalizeConnectorName(right, dataspace);
    const isDuplicate = pairs.some(([knownSource, knownTarget]) => knownSource === source && knownTarget === target);
    if (source && target && source !== target && !isDuplicate) {
      pairs.push([source, target]);
    }
  }
  return pairs;
}

function ingressBaseUrl(host: string): string {
  const protocol = (process.env.UI_INGRESS_PROTOCOL || "http").trim() || "http";
  const port = (process.env.UI_INGRESS_PORT || "").trim();
  return `${protocol}://${host}${port ? `:${port}` : ""}`;
}

function withOptionalIngressPort(urlValue: string): string {
  const port = (process.env.UI_INGRESS_PORT || process.env.PLAYWRIGHT_INGRESS_PROXY_PORT || "").trim();
  if (!port) {
    return urlValue;
  }

  try {
    const url = new URL(urlValue);
    if (!url.port) {
      url.port = port;
    }
    return url.toString().replace(/\/$/, "");
  } catch {
    return urlValue;
  }
}

function deploymentRoot(adapter: string): string {
  const projectRootPath = projectRoot();
  return path.join(projectRootPath, "deployers", adapter, "deployments");
}

function cleanSegment(value: string | undefined, fallback: string): string {
  const segment = (value || fallback || "").trim() || fallback;
  return segment.replace(/[\\/]/g, "_");
}

function normalizeTopology(value: string | undefined): string {
  const topology = (value || "local").trim().toLowerCase().replace(/_/g, "-");
  return ["local", "vm-single", "vm-distributed"].includes(topology) ? topology : "local";
}

function activeTopologyFromConfig(deployerConfig: Record<string, string>): string {
  return normalizeTopology(
    process.env.UI_TOPOLOGY ||
      process.env.PIONERA_TOPOLOGY ||
      process.env.INESDATA_TOPOLOGY ||
      deployerConfig.TOPOLOGY ||
      deployerConfig.PIONERA_TOPOLOGY,
  );
}

function commonServicesNamespace(deployerConfig: Record<string, string>): string {
  return (
    process.env.UI_COMMON_SERVICES_NAMESPACE ||
    deployerConfig.COMMON_SERVICES_NAMESPACE ||
    deployerConfig.NS_COMMON ||
    "common-srvs"
  ).trim() || "common-srvs";
}

function vmSingleEdcTransferEndpoint(deployerConfig: Record<string, string>): string {
  const namespace = commonServicesNamespace(deployerConfig);
  const serviceName = (
    process.env.UI_MINIO_SERVICE_NAME ||
    deployerConfig.MINIO_SERVICE_NAME ||
    "common-srvs-minio"
  ).trim() || "common-srvs-minio";
  const servicePort = (
    process.env.UI_MINIO_SERVICE_PORT ||
    deployerConfig.MINIO_SERVICE_PORT ||
    "9000"
  ).trim() || "9000";
  return `http://${serviceName}.${namespace}.svc:${servicePort}`;
}

function configuredTransferEndpoint(
  adapter: string,
  deployerConfig: Record<string, string>,
  credentialMinioApi: string | undefined,
  minioHost: string,
  minioProtocol: string,
): string {
  const explicitEndpoint = optionalUrl(
    process.env.UI_DEFAULT_TRANSFER_ENDPOINT ||
      deployerConfig.PIONERA_LEVEL6_TRANSFER_ENDPOINT ||
      deployerConfig.PIONERA_LEVEL6_MINIO_ENDPOINT ||
      deployerConfig.EDC_TRANSFER_ENDPOINT ||
      deployerConfig.EDC_MINIO_ENDPOINT,
  );
  if (explicitEndpoint) {
    return explicitEndpoint;
  }

  if (adapter === "edc" && activeTopologyFromConfig(deployerConfig) === "vm-single") {
    return vmSingleEdcTransferEndpoint(deployerConfig);
  }

  return credentialMinioApi || `${minioProtocol}://${minioHost}`;
}

function deploymentId(config: Record<string, string>): string {
  return cleanSegment(
    process.env.PIONERA_DEPLOYMENT_ID ||
      config.DEPLOYMENT_ID ||
      config.RUNTIME_ARTIFACT_DEPLOYMENT_ID ||
      config.VALIDATION_ENVIRONMENT_ID,
    "",
  ).replace(/^_+|_+$/g, "");
}

function configuredRuntimeDir(adapter: string, environment: string, dataspace: string): string {
  const explicitRuntimeDir = process.env.UI_RUNTIME_DIR?.trim();
  if (explicitRuntimeDir) {
    return explicitRuntimeDir;
  }
  const deployerConfig = parseKeyValueFile(deployerConfigPath(adapter));
  const topology = normalizeTopology(
    process.env.UI_TOPOLOGY ||
      process.env.PIONERA_TOPOLOGY ||
      process.env.INESDATA_TOPOLOGY ||
      deployerConfig.TOPOLOGY ||
      deployerConfig.PIONERA_TOPOLOGY,
  );
  if (topology === "local") {
    return path.join(deploymentRoot(adapter), environment, dataspace);
  }

  const parts = [deploymentRoot(adapter), environment, topology];
  const currentDeploymentId = deploymentId(deployerConfig);
  if (currentDeploymentId) {
    parts.push(currentDeploymentId);
  }
  parts.push(dataspace);
  return path.join(...parts);
}

function deployerConfigPath(adapter: string): string {
  const root = projectRoot();
  const adapterPath = path.join(root, "deployers", adapter, "deployer.config");
  if (fs.existsSync(adapterPath)) {
    return adapterPath;
  }
  return path.join(root, "deployers", "inesdata", "deployer.config");
}

function defaultPortalPath(adapter: string): string {
  return adapter === "edc" ? "/edc-dashboard/" : "/inesdata-connector-interface/";
}

function connectorCredentialsPath(
  adapter: string,
  environment: string,
  dataspace: string,
  connectorName: string,
): string {
  const envPrefix = connectorEnvPrefix(connectorName);
  const explicitPath = process.env[`UI_${envPrefix}_CREDENTIALS_FILE`]?.trim();
  if (explicitPath) {
    return explicitPath;
  }

  const runtimeDir = configuredRuntimeDir(adapter, environment, dataspace);
  const scopedPath = path.join(runtimeDir, "connectors", connectorName, "credentials.json");
  const legacyPath = path.join(runtimeDir, `credentials-connector-${connectorName}.json`);
  if (fs.existsSync(scopedPath)) {
    return scopedPath;
  }
  if (fs.existsSync(legacyPath)) {
    return legacyPath;
  }
  return scopedPath;
}

function publicAccessUrlsFromCredentials(credentials: any): Record<string, string> {
  const publicAccessUrls = stringMap(credentials?.public_access_urls);
  if (Object.keys(publicAccessUrls).length > 0) {
    return publicAccessUrls;
  }
  return stringMap(credentials?.access_urls);
}

function internalAccessUrlsFromCredentials(credentials: any): Record<string, string> {
  return stringMap(credentials?.access_urls);
}

function connectorPublicPortalBaseUrl(
  adapter: string,
  accessUrls: Record<string, string>,
): string | undefined {
  const configuredPortalUrl = optionalPortalUrl(accessUrls.connector_interface_login);
  if (configuredPortalUrl) {
    return configuredPortalUrl;
  }
  const derivedPortalUrl = appendUrlPath(accessUrls.connector_ingress, defaultPortalPath(adapter));
  return derivedPortalUrl ? withTrailingSlash(derivedPortalUrl) : undefined;
}

function connectorPublicManagementBaseUrl(accessUrls: Record<string, string>): string | undefined {
  const managementUrl = optionalUrl(accessUrls.connector_management_api);
  if (managementUrl) {
    return managementUrl.replace(/\/management\/?$/, "/management/v3");
  }
  return appendUrlPath(accessUrls.connector_ingress, "/management/v3");
}

function connectorPublicProtocolBaseUrl(accessUrls: Record<string, string>): string | undefined {
  return optionalUrl(accessUrls.connector_protocol_api) || appendUrlPath(accessUrls.connector_ingress, "/protocol");
}

function connectorProtocolAddressMode(deployerConfig: Record<string, string>, envPrefix: string): string {
  const explicitMode = (
    process.env[`UI_${envPrefix}_PROTOCOL_ADDRESS_MODE`] ||
    process.env.UI_CONNECTOR_PROTOCOL_ADDRESS_MODE ||
    deployerConfig.UI_CONNECTOR_PROTOCOL_ADDRESS_MODE ||
    ""
  ).trim();
  if (explicitMode) {
    return explicitMode.toLowerCase();
  }

  const configuredMode = (
    deployerConfig.PIONERA_CONNECTOR_PROTOCOL_ADDRESS_MODE ||
    deployerConfig.CONNECTOR_PROTOCOL_ADDRESS_MODE ||
    ""
  ).trim();
  if (configuredMode) {
    return configuredMode.toLowerCase();
  }

  const topology = (process.env.UI_TOPOLOGY || "").trim().toLowerCase();
  const adapter = normalizedAdapter();
  if (adapter === "edc" && (topology === "local" || topology === "vm-single")) {
    return "internal";
  }
  if (topology === "vm-distributed") {
    return "public";
  }

  return "public";
}

function connectorNamespaceForRole(
  adapter: string,
  deployerConfig: Record<string, string>,
  role: "provider" | "consumer" | undefined,
  dataspace: string,
): string | undefined {
  if (adapter !== "edc" || !role) {
    return undefined;
  }

  const configuredNamespace =
    role === "provider"
      ? deployerConfig.DS_1_PROVIDER_NAMESPACE
      : deployerConfig.DS_1_CONSUMER_NAMESPACE;
  const namespace = (configuredNamespace || dataspace || "").trim();
  return namespace || undefined;
}

function connectorInternalProtocolBaseUrl(
  adapter: string,
  connectorName: string,
  deployerConfig: Record<string, string>,
  role: "provider" | "consumer" | undefined,
  dataspace: string,
): string | undefined {
  const explicitRoleUrl = role
    ? process.env[`UI_${role.toUpperCase()}_INTERNAL_PROTOCOL_URL`]?.trim()
    : "";
  if (explicitRoleUrl) {
    return optionalUrl(explicitRoleUrl);
  }

  const namespace = connectorNamespaceForRole(adapter, deployerConfig, role, dataspace);
  if (!namespace) {
    return undefined;
  }

  const port = (process.env.UI_EDC_PROTOCOL_PORT || deployerConfig.EDC_PROTOCOL_PORT || "19194").trim() || "19194";
  return `http://${connectorName}.${namespace}.svc.cluster.local:${port}/protocol`;
}

function keycloakBaseUrlFromPublicAccessUrl(
  urlValue: string | undefined,
  dataspace: string,
): string | undefined {
  const normalized = optionalUrl(urlValue);
  if (!normalized) {
    return undefined;
  }

  const dataspaceNames = Array.from(new Set([dataspace, encodeURIComponent(dataspace)]));
  const suffixes = dataspaceNames.flatMap((name) => [
    `/realms/${name}/account`,
    `/realms/${name}`,
    `/admin/${name}/console`,
  ]);

  for (const suffix of suffixes) {
    if (normalized.endsWith(suffix)) {
      return withoutTrailingSlash(normalized.slice(0, -suffix.length));
    }
  }

  return normalized;
}

function publicKeycloakUrlFromCredentials(credentials: any, dataspace: string): string | undefined {
  const accessUrls = publicAccessUrlsFromCredentials(credentials);
  return (
    keycloakBaseUrlFromPublicAccessUrl(accessUrls.keycloak_realm, dataspace) ||
    keycloakBaseUrlFromPublicAccessUrl(accessUrls.keycloak_account, dataspace) ||
    keycloakBaseUrlFromPublicAccessUrl(accessUrls.keycloak_admin_console, dataspace)
  );
}

function publicKeycloakUrlFromConnectorCredentials(
  adapter: string,
  environment: string,
  dataspace: string,
  connectorNames: string[],
): string | undefined {
  for (const connectorName of connectorNames) {
    const credentials = readJsonIfExists(
      connectorCredentialsPath(adapter, environment, dataspace, connectorName),
    );
    const keycloakUrl = publicKeycloakUrlFromCredentials(credentials, dataspace);
    if (keycloakUrl) {
      return keycloakUrl;
    }
  }
  return undefined;
}

function configuredConnectorNames(adapter: string, dataspace: string): string[] {
  const deployerConfig = parseKeyValueFile(deployerConfigPath(adapter));
  return parseConnectorList(deployerConfig.DS_1_CONNECTORS, dataspace);
}

function configuredValidationPairs(adapter: string, dataspace: string): Array<[string, string]> {
  const deployerConfig = parseKeyValueFile(deployerConfigPath(adapter));
  return parseConnectorPairs(deployerConfig.DS_1_VALIDATION_PAIRS, dataspace);
}

function discoverConnectorNames(adapter: string, environment: string, dataspace: string): string[] {
  const runtimeDir = configuredRuntimeDir(adapter, environment, dataspace);
  const configuredConnectors = configuredConnectorNames(adapter, dataspace);
  if (!fs.existsSync(runtimeDir)) {
    return configuredConnectors;
  }

  const legacyConnectors = fs
    .readdirSync(runtimeDir)
    .map((entry) => {
      const match = entry.match(/^credentials-connector-(.+)\.json$/);
      return match ? match[1] : undefined;
    })
    .filter((value): value is string => Boolean(value));
  const scopedConnectorsDir = path.join(runtimeDir, "connectors");
  const scopedConnectors = fs.existsSync(scopedConnectorsDir)
    ? fs
        .readdirSync(scopedConnectorsDir)
        .filter((entry) => fs.existsSync(path.join(scopedConnectorsDir, entry, "credentials.json")))
    : [];
  const discoveredConnectors = Array.from(new Set([...legacyConnectors, ...scopedConnectors])).sort();

  if (configuredConnectors.length === 0) {
    return discoveredConnectors;
  }

  return [
    ...configuredConnectors,
    ...discoveredConnectors.filter((connector) => !configuredConnectors.includes(connector)),
  ];
}

function resolveDataspaceDefaults(): DataspaceDefaults {
  const deployerConfigPath = path.join(projectRoot(), "deployers", "inesdata", "deployer.config");
  const deployerConfig = parseKeyValueFile(deployerConfigPath);
  const infrastructureConfigPath = path.join(projectRoot(), "deployers", "infrastructure", "deployer.config");
  const infrastructureConfig = parseKeyValueFile(infrastructureConfigPath);
  const adapter = normalizedAdapter();

  return {
    adapter,
    dataspace: process.env.UI_DATASPACE || deployerConfig.DS_1_NAME || "demo",
    componentsNamespace:
      process.env.UI_COMPONENTS_NAMESPACE ||
      deployerConfig.COMPONENTS_NAMESPACE ||
      "components",
    environment: process.env.UI_ENVIRONMENT || deployerConfig.ENVIRONMENT || infrastructureConfig.ENVIRONMENT || "DEV",
    dsDomain:
      process.env.UI_DS_DOMAIN ||
      deployerConfig.DS_DOMAIN_BASE ||
      infrastructureConfig.DS_DOMAIN_BASE ||
      "dev.ds.dataspaceunit.upm",
    keycloakUrl:
      withOptionalIngressPort(
        process.env.UI_KEYCLOAK_URL ||
        deployerConfig.KC_INTERNAL_URL ||
          infrastructureConfig.KC_INTERNAL_URL ||
          deployerConfig.KC_URL ||
          infrastructureConfig.KC_URL ||
          "http://keycloak.dev.ed.dataspaceunit.upm",
      ),
    keycloakClientId: process.env.UI_KEYCLOAK_CLIENT_ID || "dataspace-users",
  };
}

function resolveConnectorRuntime(
  adapter: string,
  connectorName: string,
  dataspace: string,
  environment: string,
  dsDomain: string,
  role?: "provider" | "consumer",
): ConnectorPortalRuntime {
  const credentialsPath = connectorCredentialsPath(adapter, environment, dataspace, connectorName);
  const credentials = readJson(credentialsPath);
  const publicAccessUrls = publicAccessUrlsFromCredentials(credentials);
  const internalAccessUrls = internalAccessUrlsFromCredentials(credentials);
  const username = requiredString(credentials?.connector_user?.user, `${connectorName} username`);
  const password = requiredString(credentials?.connector_user?.passwd, `${connectorName} password`);
  const host = `${connectorName}.${dsDomain}`;
  const baseUrl = ingressBaseUrl(host);
  const deployerConfig = parseKeyValueFile(deployerConfigPath(adapter));
  const credentialMinioApi = optionalUrl(publicAccessUrls.minio_api || internalAccessUrls.minio_api);
  const minioHost = process.env.UI_MINIO_HOST || deployerConfig.MINIO_HOSTNAME || `minio.${deployerConfig.DOMAIN_BASE || "dev.ed.dataspaceunit.upm"}`;
  const minioProtocol = process.env.UI_MINIO_PROTOCOL || "http";
  const transferRegion =
    process.env.UI_TRANSFER_REGION ||
    deployerConfig.PIONERA_LEVEL6_TRANSFER_REGION ||
    deployerConfig.EDC_AWS_REGION ||
    deployerConfig.AWS_REGION ||
    "eu-central-1";
  const endpointOverride = configuredTransferEndpoint(
    adapter,
    deployerConfig,
    credentialMinioApi,
    minioHost,
    minioProtocol,
  );
  const envPrefix = connectorEnvPrefix(connectorName);
  const explicitPortalUrl = optionalPortalUrl(process.env[`UI_${envPrefix}_PORTAL_URL`]);
  const protocolMode = connectorProtocolAddressMode(deployerConfig, envPrefix);
  const protocolAccessUrls = protocolMode === "internal" ? internalAccessUrls : publicAccessUrls;
  const internalProtocolBaseUrl = connectorInternalProtocolBaseUrl(
    adapter,
    connectorName,
    deployerConfig,
    role,
    dataspace,
  );
  const transferDestinationType =
    process.env[`UI_${envPrefix}_TRANSFER_DESTINATION_TYPE`] ||
    process.env.UI_TRANSFER_DESTINATION_TYPE ||
    (adapter === "edc" ? "AmazonS3" : "InesDataStore");
  const usesObjectStorageDestination =
    adapter === "edc" && transferDestinationType.toLowerCase() !== "httpdata";
  const portalBaseUrl = withTrailingSlash(
    withOptionalIngressPort(
      withoutTrailingSlash(
        explicitPortalUrl ||
          connectorPublicPortalBaseUrl(adapter, publicAccessUrls) ||
          withTrailingSlash(`${baseUrl}${defaultPortalPath(adapter)}`),
      ),
    ),
  );
  const managementBaseUrl = withOptionalIngressPort(
    process.env[`UI_${envPrefix}_MANAGEMENT_URL`] ||
      connectorPublicManagementBaseUrl(publicAccessUrls) ||
      `${baseUrl}/management/v3`,
  );
  const protocolBaseUrl = withOptionalIngressPort(
    process.env[`UI_${envPrefix}_PROTOCOL_URL`] ||
      (protocolMode === "internal" ? internalProtocolBaseUrl : undefined) ||
      connectorPublicProtocolBaseUrl(protocolAccessUrls) ||
      `${baseUrl}/protocol`,
  );
  const transferEndpointOverride = withOptionalIngressPort(
    process.env[`UI_${envPrefix}_TRANSFER_ENDPOINT`] ||
      process.env.UI_TRANSFER_ENDPOINT ||
      endpointOverride,
  );

  return {
    adapter,
    connectorName,
    portalBaseUrl,
    managementBaseUrl,
    protocolBaseUrl,
    transferStartPath: adapter === "edc" ? "transferprocesses" : "inesdatatransferprocesses",
    transferDestinationType,
    username,
    password,
    transferDestination: usesObjectStorageDestination
      ? {
          bucketName:
            process.env[`UI_${envPrefix}_TRANSFER_BUCKET`] ||
            `${dataspace}-${connectorName}`,
          region:
            process.env[`UI_${envPrefix}_TRANSFER_REGION`] ||
            transferRegion,
          endpointOverride: transferEndpointOverride,
          accessKeyId:
            process.env[`UI_${envPrefix}_TRANSFER_ACCESS_KEY_ID`] ||
            process.env.UI_TRANSFER_ACCESS_KEY_ID ||
            requiredString(credentials?.minio?.user, `${connectorName} MinIO access key`),
          secretAccessKey:
            process.env[`UI_${envPrefix}_TRANSFER_SECRET_ACCESS_KEY`] ||
            process.env.UI_TRANSFER_SECRET_ACCESS_KEY ||
            requiredString(credentials?.minio?.passwd, `${connectorName} MinIO secret key`),
        }
      : undefined,
  };
}

export function resolveConnectorPortalRuntime(connectorName: string): ConnectorPortalRuntime {
  const defaults = resolveDataspaceDefaults();
  return resolveConnectorRuntime(
    defaults.adapter,
    connectorName,
    defaults.dataspace,
    defaults.environment,
    defaults.dsDomain,
  );
}

export function resolveDataspacePortalRuntime(): DataspacePortalRuntime {
  const defaults = resolveDataspaceDefaults();
  const discoveredConnectors = discoverConnectorNames(
    defaults.adapter,
    defaults.environment,
    defaults.dataspace,
  );
  const validationPair = configuredValidationPairs(defaults.adapter, defaults.dataspace)[0];
  const providerConnector =
    process.env.UI_PROVIDER_CONNECTOR ||
    validationPair?.[0] ||
    discoveredConnectors[0] ||
    "conn-citycouncil-demo";
  const consumerConnector =
    process.env.UI_CONSUMER_CONNECTOR ||
    validationPair?.[1] ||
    discoveredConnectors[1] ||
    "conn-company-demo";
  const keycloakUrl =
    process.env.UI_KEYCLOAK_URL ||
    publicKeycloakUrlFromConnectorCredentials(
      defaults.adapter,
      defaults.environment,
      defaults.dataspace,
      [providerConnector, consumerConnector],
    ) ||
    defaults.keycloakUrl;

  return {
    adapter: defaults.adapter,
    dataspace: defaults.dataspace,
    componentsNamespace: defaults.componentsNamespace,
    dsDomain: defaults.dsDomain,
    keycloakUrl,
    keycloakClientId: defaults.keycloakClientId,
    provider: resolveConnectorRuntime(
      defaults.adapter,
      providerConnector,
      defaults.dataspace,
      defaults.environment,
      defaults.dsDomain,
      "provider",
    ),
    consumer: resolveConnectorRuntime(
      defaults.adapter,
      consumerConnector,
      defaults.dataspace,
      defaults.environment,
      defaults.dsDomain,
      "consumer",
    ),
  };
}
