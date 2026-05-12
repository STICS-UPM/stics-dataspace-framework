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

function deploymentRoot(adapter: string): string {
  const root = projectRoot();
  return path.join(root, "deployers", adapter, "deployments");
}

function resolveConnectorMinioCredentials(
  adapter: string,
  connectorName: string,
  dataspace: string,
  environment: string,
): MinioUserCredentials {
  const credentialsPath = path.join(
    deploymentRoot(adapter),
    environment,
    dataspace,
    `credentials-connector-${connectorName}.json`,
  );
  const credentials = readJson(credentialsPath);

  return {
    username: requiredString(credentials?.minio?.user, `${connectorName} MinIO username`),
    password: requiredString(credentials?.minio?.passwd, `${connectorName} MinIO password`),
  };
}

function withNoTrailingSlash(value: string): string {
  return value.replace(/\/$/, "");
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
    process.env.UI_MINIO_CONSOLE_URL || `http://console.minio-s3.${domainBase}`;

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
