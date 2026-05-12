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
  dsDomain: string;
  keycloakUrl: string;
  keycloakClientId: string;
  provider: ConnectorPortalRuntime;
  consumer: ConnectorPortalRuntime;
};

type DataspaceDefaults = {
  adapter: string;
  dataspace: string;
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

function requiredString(value: string | undefined, label: string): string {
  if (!value || value.trim().length === 0) {
    throw new Error(`Missing value for ${label}`);
  }
  return value.trim();
}

function normalizedAdapter(): string {
  const value = (process.env.UI_ADAPTER || "inesdata").trim().toLowerCase();
  return value || "inesdata";
}

function connectorEnvPrefix(connectorName: string): string {
  return connectorName.toUpperCase().replace(/-/g, "_");
}

function ingressBaseUrl(host: string): string {
  const protocol = (process.env.UI_INGRESS_PROTOCOL || "http").trim() || "http";
  const port = (process.env.UI_INGRESS_PORT || "").trim();
  return `${protocol}://${host}${port ? `:${port}` : ""}`;
}

function withOptionalIngressPort(urlValue: string): string {
  const port = (process.env.UI_INGRESS_PORT || "").trim();
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

function defaultPortalPath(adapter: string): string {
  return adapter === "edc" ? "/edc-dashboard/" : "/inesdata-connector-interface";
}

function connectorCredentialsPath(
  adapter: string,
  environment: string,
  dataspace: string,
  connectorName: string,
): string {
  return path.join(
    deploymentRoot(adapter),
    environment,
    dataspace,
    `credentials-connector-${connectorName}.json`,
  );
}

function discoverConnectorNames(adapter: string, environment: string, dataspace: string): string[] {
  const runtimeDir = path.join(deploymentRoot(adapter), environment, dataspace);
  if (!fs.existsSync(runtimeDir)) {
    return [];
  }

  return fs
    .readdirSync(runtimeDir)
    .map((entry) => {
      const match = entry.match(/^credentials-connector-(.+)\.json$/);
      return match ? match[1] : undefined;
    })
    .filter((value): value is string => Boolean(value))
    .sort();
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
    environment: process.env.UI_ENVIRONMENT || deployerConfig.ENVIRONMENT || infrastructureConfig.ENVIRONMENT || "DEV",
    dsDomain:
      process.env.UI_DS_DOMAIN ||
      deployerConfig.DS_DOMAIN_BASE ||
      infrastructureConfig.DS_DOMAIN_BASE ||
      "dev.ds.dataspaceunit.upm",
    keycloakUrl:
      process.env.UI_KEYCLOAK_URL ||
      withOptionalIngressPort(
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
): ConnectorPortalRuntime {
  const credentialsPath = connectorCredentialsPath(adapter, environment, dataspace, connectorName);
  const credentials = readJson(credentialsPath);
  const username = requiredString(credentials?.connector_user?.user, `${connectorName} username`);
  const password = requiredString(credentials?.connector_user?.passwd, `${connectorName} password`);
  const host = `${connectorName}.${dsDomain}`;
  const baseUrl = ingressBaseUrl(host);
  const deployerConfigPath = path.join(projectRoot(), "deployers", "inesdata", "deployer.config");
  const deployerConfig = parseKeyValueFile(deployerConfigPath);
  const minioHost = process.env.UI_MINIO_HOST || deployerConfig.MINIO_HOSTNAME || `minio.${deployerConfig.DOMAIN_BASE || "dev.ed.dataspaceunit.upm"}`;
  const minioProtocol = process.env.UI_MINIO_PROTOCOL || "http";
  const transferRegion = process.env.UI_TRANSFER_REGION || "us-east-1";
  const endpointOverride = `${minioProtocol}://${minioHost}`;
  const minioAccessKey = credentials?.minio?.access_key;
  const minioSecretKey = credentials?.minio?.secret_key;
  const envPrefix = connectorEnvPrefix(connectorName);

  return {
    adapter,
    connectorName,
    portalBaseUrl:
      process.env[`UI_${envPrefix}_PORTAL_URL`] ||
      `${baseUrl}${defaultPortalPath(adapter)}`,
    managementBaseUrl:
      process.env[`UI_${envPrefix}_MANAGEMENT_URL`] ||
      `${baseUrl}/management/v3`,
    protocolBaseUrl:
      process.env[`UI_${envPrefix}_PROTOCOL_URL`] ||
      `${baseUrl}/protocol`,
    transferStartPath: adapter === "edc" ? "transferprocesses" : "inesdatatransferprocesses",
    transferDestinationType: adapter === "edc" ? "HttpData" : "InesDataStore",
    username,
    password,
    transferDestination:
      minioAccessKey && minioSecretKey
        ? {
            bucketName:
              process.env[`UI_${envPrefix}_TRANSFER_BUCKET`] ||
              `${dataspace}-${connectorName}`,
            region:
              process.env[`UI_${envPrefix}_TRANSFER_REGION`] ||
              transferRegion,
            endpointOverride:
              process.env[`UI_${envPrefix}_TRANSFER_ENDPOINT`] ||
              endpointOverride,
            accessKeyId: String(minioAccessKey),
            secretAccessKey: String(minioSecretKey),
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
  const providerConnector =
    process.env.UI_PROVIDER_CONNECTOR ||
    discoveredConnectors[0] ||
    "conn-citycouncil-demo";
  const consumerConnector =
    process.env.UI_CONSUMER_CONNECTOR ||
    discoveredConnectors[1] ||
    "conn-company-demo";

  return {
    adapter: defaults.adapter,
    dataspace: defaults.dataspace,
    dsDomain: defaults.dsDomain,
    keycloakUrl: defaults.keycloakUrl,
    keycloakClientId: defaults.keycloakClientId,
    provider: resolveConnectorRuntime(
      defaults.adapter,
      providerConnector,
      defaults.dataspace,
      defaults.environment,
      defaults.dsDomain,
    ),
    consumer: resolveConnectorRuntime(
      defaults.adapter,
      consumerConnector,
      defaults.dataspace,
      defaults.environment,
      defaults.dsDomain,
    ),
  };
}
