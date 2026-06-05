const fs = require("fs");
const path = require("path");

const RETRYABLE_STATUS_CODES = new Set([502, 503, 504]);
const DEFAULT_TOKEN_ATTEMPTS = 5;
const DEFAULT_TOKEN_RETRY_DELAY_MS = 1000;
const DEFAULT_MANAGEMENT_BRIDGE_ATTEMPTS = 4;
const DEFAULT_MANAGEMENT_BRIDGE_RETRY_DELAY_MS = 1000;

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

function cleanSegment(value, fallback) {
  const segment = String(value || fallback || "").trim() || fallback;
  return segment.replace(/[\\/]/g, "_");
}

function normalizeTopology(value) {
  const topology = String(value || "local").trim().toLowerCase().replace(/_/g, "-");
  return ["local", "vm-single", "vm-distributed"].includes(topology) ? topology : "local";
}

function deploymentId(config) {
  return cleanSegment(
    process.env.PIONERA_DEPLOYMENT_ID ||
      config.DEPLOYMENT_ID ||
      config.RUNTIME_ARTIFACT_DEPLOYMENT_ID ||
      config.VALIDATION_ENVIRONMENT_ID ||
      "",
    "",
  ).replace(/^_+|_+$/g, "");
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function positiveInt(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function findConnectorCredentialsFile(dataspace, connectorId) {
  const adapter = (
    process.env.UI_ADAPTER ||
    process.env.AI_MODEL_HUB_COMPONENT_ADAPTER ||
    process.env.PIONERA_ADAPTER ||
    "inesdata"
  ).trim().toLowerCase() || "inesdata";
  const explicitEnvPrefix = connectorId.toUpperCase().replace(/-/g, "_");
  const explicitPath = (
    process.env[`AI_MODEL_HUB_${explicitEnvPrefix}_CREDENTIALS_FILE`] ||
    process.env[`UI_${explicitEnvPrefix}_CREDENTIALS_FILE`] ||
    ""
  ).trim();
  if (explicitPath) {
    return explicitPath;
  }

  const deployerConfig = parseKeyValueFile(path.join(projectRoot(), "deployers", adapter, "deployer.config"));
  const topology = normalizeTopology(
    process.env.UI_TOPOLOGY ||
      process.env.PIONERA_TOPOLOGY ||
      process.env.INESDATA_TOPOLOGY ||
      deployerConfig.TOPOLOGY ||
      deployerConfig.PIONERA_TOPOLOGY,
  );
  const deploymentsRoot = path.join(projectRoot(), "deployers", adapter, "deployments");
  if (!fs.existsSync(deploymentsRoot)) {
    throw new Error(`Deployments directory not found: ${deploymentsRoot}`);
  }

  const candidates = [];
  const explicitRuntimeDir = (process.env.UI_RUNTIME_DIR || "").trim();
  if (explicitRuntimeDir) {
    candidates.push(path.join(explicitRuntimeDir, "connectors", connectorId, "credentials.json"));
    candidates.push(path.join(explicitRuntimeDir, `credentials-connector-${connectorId}.json`));
  }

  const configuredEnvironment = (
    process.env.UI_ENVIRONMENT ||
    deployerConfig.ENVIRONMENT ||
    "DEV"
  ).trim();
  const environments = Array.from(
    new Set([
      configuredEnvironment,
      ...fs.readdirSync(deploymentsRoot).filter((entry) =>
        fs.statSync(path.join(deploymentsRoot, entry)).isDirectory(),
      ),
    ]),
  ).filter(Boolean);

  for (const environmentDir of environments) {
    const legacyPath = path.join(deploymentsRoot, environmentDir, dataspace, `credentials-connector-${connectorId}.json`);
    const scopedParts = [
      deploymentsRoot,
      environmentDir,
      topology,
    ];
    const currentDeploymentId = deploymentId(deployerConfig);
    if (currentDeploymentId) {
      scopedParts.push(currentDeploymentId);
    }
    scopedParts.push(dataspace, "connectors", connectorId, "credentials.json");
    const scopedPath = path.join(...scopedParts);
    if (topology === "local") {
      candidates.push(legacyPath, scopedPath);
    } else {
      candidates.push(scopedPath, legacyPath);
    }
  }

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  throw new Error(
    `Connector credentials not found for ${connectorId} in dataspace ${dataspace}. Checked: ${candidates.join(", ")}`,
  );
}

function loadConnectorUserCredentials(dataspace, connectorId) {
  const credentialsFile = findConnectorCredentialsFile(dataspace, connectorId);
  const payload = JSON.parse(fs.readFileSync(credentialsFile, "utf8"));
  const connectorUser = payload.connector_user || {};
  if (!connectorUser.user || !connectorUser.passwd) {
    throw new Error(`connector_user credentials missing in ${credentialsFile}`);
  }
  return connectorUser;
}

async function requestConnectorManagementToken(runtime, connectorId) {
  const connectorUser = loadConnectorUserCredentials(runtime.dataspace, connectorId);
  const tokenEndpoint = `${runtime.keycloakBaseUrl}/realms/${runtime.dataspace}/protocol/openid-connect/token`;
  const attempts = positiveInt(process.env.AI_MODEL_HUB_TOKEN_REQUEST_ATTEMPTS, DEFAULT_TOKEN_ATTEMPTS);
  const retryDelayMs = positiveInt(
    process.env.AI_MODEL_HUB_TOKEN_REQUEST_RETRY_DELAY_MS,
    DEFAULT_TOKEN_RETRY_DELAY_MS,
  );

  const body = new URLSearchParams({
    grant_type: "password",
    client_id: "dataspace-users",
    username: connectorUser.user,
    password: connectorUser.passwd,
    scope: "openid profile email",
  });

  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(tokenEndpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: body.toString(),
      });

      if (!response.ok) {
        const error = new Error(`Token request failed for ${connectorId}: HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }

      const payload = await response.json();
      if (!payload.access_token) {
        throw new Error(`Token response for ${connectorId} does not contain access_token`);
      }

      return payload.access_token;
    } catch (error) {
      lastError = error;
      const status = error && typeof error.status === "number" ? error.status : null;
      const retryable = status === null || RETRYABLE_STATUS_CODES.has(status);
      if (!retryable || attempt >= attempts) {
        break;
      }
      await delay(retryDelayMs);
    }
  }

  throw lastError || new Error(`Token request failed for ${connectorId}`);
}

async function buildManagementAuthorizationHeaders(runtime) {
  const [providerToken, consumerToken] = await Promise.all([
    requestConnectorManagementToken(runtime, runtime.providerConnectorId),
    requestConnectorManagementToken(runtime, runtime.consumerConnectorId),
  ]);

  return {
    [runtime.providerConnectorId]: `Bearer ${providerToken}`,
    [runtime.consumerConnectorId]: `Bearer ${consumerToken}`,
  };
}

function trimTrailingSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function normalize(value) {
  return String(value || "").trim().toLowerCase();
}

function connectorDescriptors(runtime, authorizationByConnector) {
  return [
    {
      connectorId: runtime.providerConnectorId,
      connectorName: runtime.providerConnectorName || "Provider",
      managementUrl: runtime.providerManagementUrl,
      defaultUrl: runtime.providerDefaultUrl,
      protocolUrl: runtime.providerProtocolUrl,
      authorization: authorizationByConnector[runtime.providerConnectorId],
    },
    {
      connectorId: runtime.consumerConnectorId,
      connectorName: runtime.consumerConnectorName || "Consumer",
      managementUrl: runtime.consumerManagementUrl,
      defaultUrl: runtime.consumerDefaultUrl,
      protocolUrl: runtime.consumerProtocolUrl,
      authorization: authorizationByConnector[runtime.consumerConnectorId],
    },
  ].filter((descriptor) => descriptor.connectorId);
}

function matchesConnectorSegment(segment, descriptor) {
  const normalizedSegment = normalize(decodeURIComponent(segment || ""));
  return (
    normalizedSegment === normalize(descriptor.connectorId) ||
    normalizedSegment === normalize(descriptor.connectorName)
  );
}

function connectorForDirectConnectorRequest(requestUrl, descriptors) {
  const requestHref = trimTrailingSlash(requestUrl.href.split("?")[0]);
  const requestHost = normalize(requestUrl.hostname);

  for (const descriptor of descriptors) {
    const directUrls = [
      ["management", descriptor.managementUrl],
      ["api", descriptor.defaultUrl],
      ["protocol", descriptor.protocolUrl],
    ];

    for (const [serviceName, directUrl] of directUrls) {
      const normalizedDirectUrl = trimTrailingSlash(directUrl);
      if (!normalizedDirectUrl) {
        continue;
      }
      const directHost = normalize(new URL(normalizedDirectUrl).hostname);
      const hostMatchesLegacyConnectorSubdomain = serviceName === "management"
        && requestHost.startsWith(normalize(descriptor.connectorId));

      if (
        hostMatchesLegacyConnectorSubdomain ||
        (directHost && requestHost === directHost && requestHref.startsWith(normalizedDirectUrl))
      ) {
        return {
          descriptor,
          serviceName,
        };
      }
    }
  }

  return null;
}

function parseDashboardProxyPath(requestUrl, descriptors) {
  const match = requestUrl.pathname.match(
    /^\/edc-dashboard-api\/connectors\/([^/]+)\/([^/]+)(?:\/(.*))?$/,
  );
  if (!match) {
    return null;
  }

  const [, connectorSegment, serviceName, remainingPath = ""] = match;
  const descriptor = descriptors.find((candidate) => matchesConnectorSegment(connectorSegment, candidate));
  if (!descriptor) {
    return null;
  }

  return {
    descriptor,
    serviceName: normalize(serviceName),
    remainingPath,
  };
}

function targetUrlForProxyRequest(proxyRequest, queryString) {
  const { descriptor, serviceName, remainingPath } = proxyRequest;
  const rest = String(remainingPath || "").replace(/^\/+/, "");
  const baseUrlByService = {
    management: descriptor.managementUrl,
    api: descriptor.defaultUrl,
    protocol: descriptor.protocolUrl,
  };
  const baseUrl = trimTrailingSlash(baseUrlByService[serviceName]);
  if (!baseUrl) {
    return null;
  }

  const targetUrl = rest ? `${baseUrl}/${rest}` : baseUrl;
  return queryString ? `${targetUrl}${queryString}` : targetUrl;
}

function filteredHeaders(headers, authorization) {
  const forwarded = {};
  for (const [key, value] of Object.entries(headers || {})) {
    const normalized = key.toLowerCase();
    if (["host", "cookie", "content-length", "authorization"].includes(normalized)) {
      continue;
    }
    forwarded[key] = value;
  }

  if (authorization) {
    forwarded.authorization = authorization;
  }
  return forwarded;
}

function responseHeaders(headers) {
  const forwarded = {};
  headers.forEach((value, key) => {
    if (!["content-length", "transfer-encoding"].includes(key.toLowerCase())) {
      forwarded[key] = value;
    }
  });
  return forwarded;
}

function shouldRetryManagementBridge(url, method, status) {
  const normalizedMethod = String(method || "").toUpperCase();
  if (!["GET", "HEAD"].includes(normalizedMethod) || !RETRYABLE_STATUS_CODES.has(status)) {
    return false;
  }

  try {
    return new URL(url).pathname.toLowerCase().endsWith("/dataplanes");
  } catch {
    return false;
  }
}

async function fetchManagementBridge(url, options) {
  const attempts = positiveInt(
    process.env.AI_MODEL_HUB_MANAGEMENT_BRIDGE_ATTEMPTS,
    DEFAULT_MANAGEMENT_BRIDGE_ATTEMPTS,
  );
  const retryDelayMs = positiveInt(
    process.env.AI_MODEL_HUB_MANAGEMENT_BRIDGE_RETRY_DELAY_MS,
    DEFAULT_MANAGEMENT_BRIDGE_RETRY_DELAY_MS,
  );
  const method = options.method || "GET";
  let lastError = null;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, options);
      if (!shouldRetryManagementBridge(url, method, response.status) || attempt >= attempts) {
        return response;
      }
    } catch (error) {
      lastError = error;
      if (attempt >= attempts) {
        break;
      }
    }
    await delay(retryDelayMs);
  }

  throw lastError || new Error(`Management bridge request failed for ${url}`);
}

function corsHeaders(requestHeaders) {
  const origin = requestHeaders.origin || "*";
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "access-control-allow-headers":
      requestHeaders["access-control-request-headers"] || "authorization,content-type,accept",
    "access-control-allow-credentials": "true",
  };
}

function authorizationForService(connectorRequest) {
  if (!connectorRequest || !connectorRequest.descriptor) {
    return undefined;
  }
  if (connectorRequest.serviceName === "protocol") {
    return undefined;
  }
  return connectorRequest.descriptor.authorization;
}

async function fulfillDirectConnectorRequest(route, connectorRequest) {
  const request = route.request();
  const headers = request.headers();

  if (request.method().toUpperCase() === "OPTIONS") {
    await route.fulfill({
      status: 204,
      headers: corsHeaders(headers),
      body: "",
    });
    return;
  }

  const response = await fetchManagementBridge(request.url(), {
    method: request.method(),
    headers: filteredHeaders(headers, authorizationForService(connectorRequest)),
    body: ["GET", "HEAD"].includes(request.method().toUpperCase()) ? undefined : request.postDataBuffer(),
  });

  await route.fulfill({
    status: response.status,
    headers: {
      ...responseHeaders(response.headers),
      ...corsHeaders(headers),
    },
    body: Buffer.from(await response.arrayBuffer()),
  });
}

async function fulfillDashboardProxyRequest(route, proxyRequest, requestUrl) {
  if (proxyRequest.serviceName === "api" && /^check\/health\/?$/i.test(proxyRequest.remainingPath)) {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        isSystemHealthy: true,
        connectorName: proxyRequest.descriptor.connectorName,
        authMode: "playwright-route-bridge",
      }),
    });
    return;
  }

  const targetUrl = targetUrlForProxyRequest(proxyRequest, requestUrl.search);
  if (!targetUrl) {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        message: `Unsupported dashboard bridge path: ${requestUrl.pathname}`,
      }),
    });
    return;
  }

  const request = route.request();
  const method = request.method();
  const response = await fetchManagementBridge(targetUrl, {
    method,
    headers: filteredHeaders(
      request.headers(),
      proxyRequest.serviceName === "protocol" ? undefined : proxyRequest.descriptor.authorization,
    ),
    body: ["GET", "HEAD"].includes(method.toUpperCase()) ? undefined : request.postDataBuffer(),
  });

  await route.fulfill({
    status: response.status,
    headers: responseHeaders(response.headers),
    body: Buffer.from(await response.arrayBuffer()),
  });
}

async function attachManagementAuthorizationRoutes(page, runtime) {
  const authorizationByConnector = await buildManagementAuthorizationHeaders(runtime);
  const descriptors = connectorDescriptors(runtime, authorizationByConnector);

  const routeHandler = async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const proxyRequest = parseDashboardProxyPath(requestUrl, descriptors);

    if (proxyRequest) {
      await fulfillDashboardProxyRequest(route, proxyRequest, requestUrl);
      return;
    }

    const connectorRequest = connectorForDirectConnectorRequest(requestUrl, descriptors);
    if (!connectorRequest) {
      await route.continue();
      return;
    }

    await fulfillDirectConnectorRequest(route, connectorRequest);
  };

  await page.route("**/*", routeHandler);
  await page.route("**/edc-dashboard-api/connectors/**", routeHandler);

  return authorizationByConnector;
}

module.exports = {
  attachManagementAuthorizationRoutes,
  findConnectorCredentialsFile,
  loadConnectorUserCredentials,
  requestConnectorManagementToken,
};
