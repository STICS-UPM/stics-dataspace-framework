import type { Page, Route } from "@playwright/test";

import type { DataspacePortalRuntime } from "./dataspace-runtime";

function parseHosts(rawValue: string | undefined): string[] {
  return String(rawValue || "")
    .split(",")
    .map((entry) => entry.trim().replace(/\.$/, "").toLowerCase())
    .filter(Boolean);
}

function hostFromUrl(urlValue: string): string | undefined {
  try {
    return new URL(urlValue).hostname.toLowerCase();
  } catch {
    return undefined;
  }
}

function defaultHosts(runtime: DataspacePortalRuntime): string[] {
  const hosts = new Set<string>();
  for (const url of [
    runtime.keycloakUrl,
    runtime.provider.portalBaseUrl,
    runtime.provider.managementBaseUrl,
    runtime.provider.protocolBaseUrl,
    runtime.consumer.portalBaseUrl,
    runtime.consumer.managementBaseUrl,
    runtime.consumer.protocolBaseUrl,
  ]) {
    const host = hostFromUrl(url);
    if (host) {
      hosts.add(host);
    }
  }

  const keycloakHost = hostFromUrl(runtime.keycloakUrl);
  if (keycloakHost?.startsWith("auth.")) {
    hosts.add(`admin.${keycloakHost}`);
  }

  return Array.from(hosts);
}

function filteredHeaders(route: Route, originalHost: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const [key, value] of Object.entries(route.request().headers())) {
    const normalized = key.toLowerCase();
    if (normalized === "host" || normalized === "content-length") {
      continue;
    }
    headers[key] = value;
  }
  headers.Host = originalHost;
  return headers;
}

export async function installIngressPortForwardRouteBridge(
  page: Page,
  runtime: DataspacePortalRuntime,
): Promise<() => Promise<void>> {
  const proxyPort = (process.env.PLAYWRIGHT_INGRESS_PROXY_PORT || process.env.UI_INGRESS_PORT || "").trim();
  if (!proxyPort) {
    return async () => {};
  }

  const proxyHost = (process.env.PLAYWRIGHT_INGRESS_PROXY_HOST || "127.0.0.1").trim();
  const hosts = new Set([
    ...defaultHosts(runtime),
    ...parseHosts(process.env.PLAYWRIGHT_INGRESS_PROXY_HOSTS),
  ]);
  if (hosts.size === 0) {
    return async () => {};
  }

  const routeHandler = async (route: Route) => {
    const requestUrl = new URL(route.request().url());
    const hostname = requestUrl.hostname.toLowerCase();
    if (!hosts.has(hostname)) {
      await route.continue();
      return;
    }

    const targetUrl = `http://${proxyHost}:${proxyPort}${requestUrl.pathname}${requestUrl.search}`;
    const upstreamResponse = await route.fetch({
      url: targetUrl,
      headers: filteredHeaders(route, requestUrl.host),
      maxRedirects: 0,
    });
    await route.fulfill({ response: upstreamResponse });
  };

  await page.route("**/*", routeHandler);
  return async () => {
    await page.unroute("**/*", routeHandler);
  };
}
