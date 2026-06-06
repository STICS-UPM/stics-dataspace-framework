import { request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page, Route } from "@playwright/test";

import type {
  ConnectorPortalRuntime,
  DataspacePortalRuntime,
} from "./dataspace-runtime";

type TokenCache = Map<string, string>;

const EDC_COUNTER_PARTY_ADDRESS_IRI = "https://w3id.org/edc/v0.0.1/ns/counterPartyAddress";
const EDC_COUNTER_PARTY_ID_IRI = "https://w3id.org/edc/v0.0.1/ns/counterPartyId";
const EDC_PROTOCOL_IRI = "https://w3id.org/edc/v0.0.1/ns/protocol";

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function ingressProxyTarget(urlValue: string): { url: string; hostHeader?: string } {
  const proxyPort = (process.env.PLAYWRIGHT_INGRESS_PROXY_PORT || process.env.UI_INGRESS_PORT || "").trim();
  if (!proxyPort) {
    return { url: urlValue };
  }

  let parsed: URL;
  try {
    parsed = new URL(urlValue);
  } catch {
    return { url: urlValue };
  }

  const hostname = parsed.hostname.toLowerCase();
  if (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1") {
    return { url: urlValue };
  }

  const proxyHost = (process.env.PLAYWRIGHT_INGRESS_PROXY_HOST || "127.0.0.1").trim();
  return {
    url: `http://${proxyHost}:${proxyPort}${parsed.pathname}${parsed.search}`,
    hostHeader: parsed.host,
  };
}

async function issueConnectorToken(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  connector: ConnectorPortalRuntime,
  cache: TokenCache,
): Promise<string> {
  const cached = cache.get(connector.connectorName);
  if (cached) {
    return cached;
  }

  const response = await request.post(
    `${runtime.keycloakUrl}/realms/${runtime.dataspace}/protocol/openid-connect/token`,
    {
      form: {
        grant_type: "password",
        client_id: runtime.keycloakClientId,
        username: connector.username,
        password: connector.password,
        scope: "openid profile email",
      },
    },
  );

  if (!response.ok()) {
    throw new Error(
      `Failed to issue token for connector '${connector.connectorName}' with HTTP ${response.status()}`,
    );
  }

  const payload = await response.json();
  const token = payload?.access_token;
  if (!token) {
    throw new Error(`Token response for connector '${connector.connectorName}' does not contain access_token`);
  }

  cache.set(connector.connectorName, token);
  return token;
}

function resolveConnectorRuntime(
  runtime: DataspacePortalRuntime,
  connectorName: string,
): ConnectorPortalRuntime {
  if (runtime.provider.connectorName === connectorName) {
    return runtime.provider;
  }
  if (runtime.consumer.connectorName === connectorName) {
    return runtime.consumer;
  }
  throw new Error(`Unknown connector in dashboard bridge: ${connectorName}`);
}

function otherConnectorRuntime(
  runtime: DataspacePortalRuntime,
  connectorName: string,
): ConnectorPortalRuntime {
  if (runtime.provider.connectorName === connectorName) {
    return runtime.consumer;
  }
  if (runtime.consumer.connectorName === connectorName) {
    return runtime.provider;
  }
  throw new Error(`Unknown connector in dashboard bridge: ${connectorName}`);
}

function targetUrlFor(
  connector: ConnectorPortalRuntime,
  serviceName: string,
  remainingPath: string,
): string | null {
  const rest = remainingPath.replace(/^\/+/, "");

  if (serviceName === "management") {
    const suffix = rest.replace(/^v3\/?/, "");
    return suffix
      ? `${trimTrailingSlash(connector.managementBaseUrl)}/${suffix}`
      : trimTrailingSlash(connector.managementBaseUrl);
  }

  if (serviceName === "protocol") {
    return rest
      ? `${trimTrailingSlash(connector.protocolBaseUrl)}/${rest}`
      : trimTrailingSlash(connector.protocolBaseUrl);
  }

  if (serviceName === "api" && /^check\/health\/?$/i.test(rest)) {
    return null;
  }

  return null;
}

function isCatalogRequest(
  serviceName: string,
  remainingPath: string,
  method: string,
): boolean {
  if (serviceName !== "management" || method.toUpperCase() !== "POST") {
    return false;
  }

  const rest = remainingPath.replace(/^\/+/, "");
  return /^v3\/catalog\/request\/?$/i.test(rest) || /^catalog\/request\/?$/i.test(rest);
}

function textValue(payload: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return value.trim();
    }
    if (
      Array.isArray(value) &&
      value.length > 0 &&
      typeof value[0] === "object" &&
      value[0] !== null &&
      typeof (value[0] as Record<string, unknown>)["@value"] === "string"
    ) {
      const expandedValue = ((value[0] as Record<string, unknown>)["@value"] as string).trim();
      if (expandedValue) {
        return expandedValue;
      }
    }
  }
  return undefined;
}

function hasUsableCounterPartyAddress(value: string | undefined): boolean {
  if (!value) {
    return false;
  }
  return /^(https?:\/\/|wss?:\/\/)/i.test(value);
}

function requestedCounterPartyRuntime(
  runtime: DataspacePortalRuntime,
  currentConnectorName: string,
  payload: Record<string, unknown>,
): ConnectorPortalRuntime {
  const requestedId = textValue(payload, [
    "counterPartyId",
    "edc:counterPartyId",
    EDC_COUNTER_PARTY_ID_IRI,
    "connectorId",
  ]);

  if (requestedId) {
    if (requestedId === runtime.provider.connectorName) {
      return runtime.provider;
    }
    if (requestedId === runtime.consumer.connectorName) {
      return runtime.consumer;
    }
  }

  return otherConnectorRuntime(runtime, currentConnectorName);
}

function counterPartyFromDashboardPath(
  runtime: DataspacePortalRuntime,
  value: string | undefined,
): ConnectorPortalRuntime | undefined {
  if (!value) {
    return undefined;
  }

  const match = value.match(/\/edc-dashboard-api\/connectors\/([^/]+)\/protocol\/?$/i);
  if (!match) {
    return undefined;
  }

  const connectorName = decodeURIComponent(match[1]);
  if (connectorName === runtime.provider.connectorName) {
    return runtime.provider;
  }
  if (connectorName === runtime.consumer.connectorName) {
    return runtime.consumer;
  }
  return undefined;
}

function defaultQuerySpec(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {
    offset: 0,
    limit: 100,
    filterExpression: [],
  };
}

function catalogRequestCompatibilityAliasesEnabled(): boolean {
  return ["1", "true", "yes"].includes(
    (process.env.UI_EDC_CATALOG_REQUEST_COMPAT_ALIASES || "").trim().toLowerCase(),
  );
}

function normalizedCatalogRequestData(
  route: Route,
  runtime: DataspacePortalRuntime,
  connectorName: string,
  serviceName: string,
  remainingPath: string,
): Buffer | undefined {
  const originalData = route.request().postDataBuffer() ?? undefined;
  if (!originalData || !isCatalogRequest(serviceName, remainingPath, route.request().method())) {
    return originalData;
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(originalData.toString("utf8"));
  } catch {
    return originalData;
  }

  const currentAddress = textValue(payload, [
    "counterPartyAddress",
    "edc:counterPartyAddress",
    EDC_COUNTER_PARTY_ADDRESS_IRI,
  ]);
  const counterParty =
    counterPartyFromDashboardPath(runtime, currentAddress) ||
    requestedCounterPartyRuntime(runtime, connectorName, payload);
  const counterPartyAddress = counterParty.protocolBaseUrl || currentAddress;
  if (!hasUsableCounterPartyAddress(counterPartyAddress)) {
    return originalData;
  }
  payload["@context"] = {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    ...((payload["@context"] && typeof payload["@context"] === "object") ? payload["@context"] as Record<string, unknown> : {}),
  };
  payload["@type"] = typeof payload["@type"] === "string" ? payload["@type"] : "CatalogRequest";
  payload.counterPartyAddress = counterPartyAddress;
  delete payload["edc:counterPartyAddress"];
  delete payload[EDC_COUNTER_PARTY_ADDRESS_IRI];

  const currentId = textValue(payload, [
    "counterPartyId",
    "edc:counterPartyId",
    EDC_COUNTER_PARTY_ID_IRI,
  ]);
  if (!currentId) {
    payload.counterPartyId = counterParty.connectorName;
  }
  delete payload["edc:counterPartyId"];
  delete payload[EDC_COUNTER_PARTY_ID_IRI];

  const currentProtocol = textValue(payload, ["protocol", "edc:protocol", EDC_PROTOCOL_IRI]);
  if (!currentProtocol) {
    payload.protocol = "dataspace-protocol-http";
  }
  delete payload["edc:protocol"];
  delete payload[EDC_PROTOCOL_IRI];
  payload.querySpec = defaultQuerySpec(payload.querySpec);

  if (catalogRequestCompatibilityAliasesEnabled()) {
    payload["@context"] = {
      ...((payload["@context"] && typeof payload["@context"] === "object") ? payload["@context"] as Record<string, unknown> : {}),
      edc: "https://w3id.org/edc/v0.0.1/ns/",
    };
    payload["edc:counterPartyAddress"] = counterPartyAddress;
    payload[EDC_COUNTER_PARTY_ADDRESS_IRI] = counterPartyAddress;
    payload["edc:counterPartyId"] = payload.counterPartyId;
    payload[EDC_COUNTER_PARTY_ID_IRI] = payload.counterPartyId;
    payload["edc:protocol"] = payload.protocol;
    payload[EDC_PROTOCOL_IRI] = payload.protocol;
  }

  return Buffer.from(JSON.stringify(payload));
}

function filteredHeaders(route: Route, bearerToken?: string, hostHeader?: string): Record<string, string> {
  const requestHeaders = route.request().headers();
  const headers: Record<string, string> = {};

  for (const [key, value] of Object.entries(requestHeaders)) {
    const normalized = key.toLowerCase();
    if (normalized === "host" || normalized === "cookie" || normalized === "content-length" || normalized === "authorization") {
      continue;
    }
    headers[key] = value;
  }

  if (bearerToken) {
    headers.Authorization = `Bearer ${bearerToken}`;
  }
  if (hostHeader) {
    headers.Host = hostHeader;
  }

  return headers;
}

async function fulfillRoute(
  route: Route,
  response: Parameters<Route["fulfill"]>[0],
): Promise<void> {
  try {
    await route.fulfill(response);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (/Route is already handled/i.test(message)) {
      return;
    }
    throw error;
  }
}

async function passThroughRoute(route: Route): Promise<void> {
  const fallback = (route as Route & { fallback?: () => Promise<void> }).fallback;
  if (typeof fallback === "function") {
    await fallback.call(route);
    return;
  }
  await route.continue();
}

export async function installEdcDashboardRouteBridge(
  page: Page,
  runtime: DataspacePortalRuntime,
): Promise<() => Promise<void>> {
  if (runtime.adapter !== "edc") {
    return async () => {};
  }

  const bridgeRequest = await playwrightRequest.newContext();
  const tokenCache: TokenCache = new Map();

  const routeHandler = async (route: Route) => {
    const requestUrl = new URL(route.request().url());
    const relativePath = requestUrl.pathname.replace(/^\/edc-dashboard-api\/connectors\//, "");
    const segments = relativePath.split("/").filter(Boolean);
    const [connectorName, serviceName, ...restSegments] = segments;

    if (!connectorName || !serviceName) {
      await fulfillRoute(route, {
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ message: "Connector or service segment missing" }),
      });
      return;
    }

    const remainingPath = restSegments.join("/");
    if (serviceName === "api" && /^check\/health\/?$/i.test(remainingPath)) {
      await fulfillRoute(route, {
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          isSystemHealthy: true,
          connectorName,
          authMode: "playwright-route-bridge",
        }),
      });
      return;
    }

    if (serviceName === "api" || serviceName === "control") {
      await passThroughRoute(route);
      return;
    }

    const connector = resolveConnectorRuntime(runtime, connectorName);
    const targetUrl = targetUrlFor(connector, serviceName, remainingPath);
    if (!targetUrl) {
      await fulfillRoute(route, {
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ message: `Unsupported dashboard bridge path: ${requestUrl.pathname}` }),
      });
      return;
    }

    const bearerToken = serviceName === "management"
      ? await issueConnectorToken(bridgeRequest, runtime, connector, tokenCache)
      : undefined;

    const targetUrlWithQuery = requestUrl.search
      ? `${targetUrl}${requestUrl.search}`
      : targetUrl;

    const upstreamTarget = ingressProxyTarget(targetUrlWithQuery);
    const upstreamResponse = await bridgeRequest.fetch(upstreamTarget.url, {
      method: route.request().method(),
      headers: filteredHeaders(route, bearerToken, upstreamTarget.hostHeader),
      data: normalizedCatalogRequestData(route, runtime, connectorName, serviceName, remainingPath),
    });

    await fulfillRoute(route, {
      status: upstreamResponse.status(),
      headers: upstreamResponse.headers(),
      body: await upstreamResponse.body(),
    });
  };

  await page.route("**/edc-dashboard-api/connectors/**", routeHandler);

  return async () => {
    await page.unroute("**/edc-dashboard-api/connectors/**", routeHandler);
    await bridgeRequest.dispose();
  };
}
