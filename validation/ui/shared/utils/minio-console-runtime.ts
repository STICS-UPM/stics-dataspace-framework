import fs from "fs";
import path from "path";

type MinioUserCredentials = {
  username: string;
  password: string;
};

export type MinioBucketTarget = {
  role: "provider" | "consumer";
  connectorName: string;
  bucketName: string;
  bucketBrowserUrl: string;
  credentials: MinioUserCredentials;
  expectedObject?: string;
};

export type MinioConsoleRuntime = {
  adapter: string;
  consoleBaseUrl: string;
  dataspace: string;
  environment: string;
  targets: MinioBucketTarget[];
};

function projectRoot(): string {
  return path.resolve(__dirname, "../../../..");
}

function parseKeyValueFile(filePath: string): Record<string, string> {
  if (!fs.existsSync(filePath)) {
    return {};
  }
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

function normalizedAdapter(): string {
  const value = (process.env.UI_ADAPTER || "inesdata").trim().toLowerCase();
  return value || "inesdata";
}

function deploymentRoot(adapter: string): string {
  const root = projectRoot();
  return path.join(root, "deployers", adapter, "deployments");
}

function cleanSegment(value: string | undefined, fallback: string): string {
  const segment = (value || fallback || "").trim() || fallback;
  return segment.replace(/[\\/]/g, "_");
}

function normalizeTopology(value: string | undefined): string {
  const topology = (value || "local").trim().toLowerCase().replace(/_/g, "-");
  return ["local", "vm-single", "vm-distributed"].includes(topology) ? topology : "local";
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

function configuredRuntimeDir(
  adapter: string,
  dataspace: string,
  environment: string,
): string {
  const explicitRuntimeDir = process.env.UI_RUNTIME_DIR?.trim();
  if (explicitRuntimeDir) {
    return explicitRuntimeDir;
  }

  const deployerConfigPath = path.join(projectRoot(), "deployers", adapter, "deployer.config");
  const deployerConfig = parseKeyValueFile(deployerConfigPath);
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

function connectorCredentialsPath(
  adapter: string,
  connectorName: string,
  dataspace: string,
  environment: string,
): string {
  const envPrefix = connectorName.toUpperCase().replace(/-/g, "_");
  const explicitPath = process.env[`UI_${envPrefix}_CREDENTIALS_FILE`]?.trim();
  if (explicitPath) {
    return explicitPath;
  }

  const runtimeDir = configuredRuntimeDir(adapter, dataspace, environment);
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

function resolveConnectorMinioCredentials(
  adapter: string,
  connectorName: string,
  dataspace: string,
  environment: string,
): MinioUserCredentials {
  const credentialsPath = connectorCredentialsPath(adapter, connectorName, dataspace, environment);
  const credentials = readJson(credentialsPath);

  return {
    username: requiredString(credentials?.minio?.user, `${connectorName} MinIO username`),
    password: requiredString(credentials?.minio?.passwd, `${connectorName} MinIO password`),
  };
}

function withNoTrailingSlash(value: string): string {
  return value.replace(/\/$/, "");
}

function publicMinioConsoleUrlFromCredentials(
  adapter: string,
  connectorName: string,
  dataspace: string,
  environment: string,
): string | undefined {
  const credentials = readJsonIfExists(
    connectorCredentialsPath(adapter, connectorName, dataspace, environment),
  );
  const value = credentials?.public_access_urls?.minio_console;
  if (typeof value !== "string" || value.trim().length === 0) {
    return undefined;
  }
  return value.trim();
}

function buildBucketTarget(opts: {
  adapter: string;
  role: "provider" | "consumer";
  connectorName: string;
  dataspace: string;
  environment: string;
  consoleBaseUrl: string;
  bucketOverride?: string;
  expectedObject?: string;
}): MinioBucketTarget {
  const bucketName = opts.bucketOverride || `${opts.dataspace}-${opts.connectorName}`;

  return {
    role: opts.role,
    connectorName: opts.connectorName,
    bucketName,
    bucketBrowserUrl: `${withNoTrailingSlash(opts.consoleBaseUrl)}/browser/${bucketName}`,
    credentials: resolveConnectorMinioCredentials(
      opts.adapter,
      opts.connectorName,
      opts.dataspace,
      opts.environment,
    ),
    expectedObject: opts.expectedObject,
  };
}

export function resolveMinioConsoleRuntime(overrides?: {
  providerExpectedObject?: string;
  consumerExpectedObject?: string;
}): MinioConsoleRuntime {
  const deployerConfigPath = path.join(projectRoot(), "deployers", "inesdata", "deployer.config");
  const deployerConfig = parseKeyValueFile(deployerConfigPath);
  const adapter = normalizedAdapter();

  const dataspace = process.env.UI_DATASPACE || deployerConfig.DS_1_NAME || "demo";
  const environment = process.env.UI_ENVIRONMENT || deployerConfig.ENVIRONMENT || "DEV";
  const domainBase = process.env.UI_DOMAIN_BASE || deployerConfig.DOMAIN_BASE || "dev.ed.dataspaceunit.upm";
  const providerConnector = process.env.UI_PROVIDER_CONNECTOR || "conn-citycouncil-demo";
  const consumerConnector = process.env.UI_CONSUMER_CONNECTOR || "conn-company-demo";
  const consoleBaseUrl =
    process.env.UI_MINIO_CONSOLE_URL ||
    deployerConfig.MINIO_CONSOLE_PUBLIC_URL ||
    publicMinioConsoleUrlFromCredentials(adapter, providerConnector, dataspace, environment) ||
    `http://console.minio-s3.${domainBase}`;

  return {
    adapter,
    consoleBaseUrl,
    dataspace,
    environment,
    targets: [
      buildBucketTarget({
        adapter,
        role: "provider",
        connectorName: providerConnector,
        dataspace,
        environment,
        consoleBaseUrl,
        bucketOverride: process.env.UI_MINIO_PROVIDER_BUCKET,
        expectedObject: overrides?.providerExpectedObject || process.env.UI_MINIO_PROVIDER_EXPECT_OBJECT,
      }),
      buildBucketTarget({
        adapter,
        role: "consumer",
        connectorName: consumerConnector,
        dataspace,
        environment,
        consoleBaseUrl,
        bucketOverride: process.env.UI_MINIO_CONSUMER_BUCKET,
        expectedObject: overrides?.consumerExpectedObject || process.env.UI_MINIO_CONSUMER_EXPECT_OBJECT,
      }),
    ],
  };
}
