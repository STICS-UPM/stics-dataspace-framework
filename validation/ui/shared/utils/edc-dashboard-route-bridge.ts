import { request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page, Route } from "@playwright/test";

import type {
  ConnectorPortalRuntime,
  DataspacePortalRuntime,
} from "./dataspace-runtime";

type TokenCache = Map<string, string>;

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
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

function filteredHeaders(route: Route, bearerToken?: string): Record<string, string> {
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

  return headers;
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
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ message: "Connector or service segment missing" }),
      });
      return;
    }

    const remainingPath = restSegments.join("/");
    if (serviceName === "api" && /^check\/health\/?$/i.test(remainingPath)) {
      await route.fulfill({
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

    const connector = resolveConnectorRuntime(runtime, connectorName);
    const targetUrl = targetUrlFor(connector, serviceName, remainingPath);
    if (!targetUrl) {
      await route.fulfill({
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

    const upstreamResponse = await bridgeRequest.fetch(targetUrlWithQuery, {
      method: route.request().method(),
      headers: filteredHeaders(route, bearerToken),
      data: route.request().postDataBuffer() ?? undefined,
    });

    await route.fulfill({
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
