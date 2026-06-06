function withoutTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function normalizePath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "/";
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function appendUrlPath(baseUrl: string, pathValue: string): string {
  return `${withoutTrailingSlash(baseUrl.trim())}${normalizePath(pathValue)}`;
}

function forceUrlScheme(baseUrl: string, scheme: string): string {
  const rawValue = withoutTrailingSlash(baseUrl.trim());
  if (!rawValue) {
    return "";
  }
  const withScheme = rawValue.includes("://") ? rawValue : `${scheme}://${rawValue}`;
  try {
    const parsed = new URL(withScheme);
    parsed.protocol = `${scheme}:`;
    parsed.search = "";
    parsed.hash = "";
    return withoutTrailingSlash(parsed.toString());
  } catch {
    return "";
  }
}

function isVmDistributedTopology(): boolean {
  return (process.env.UI_TOPOLOGY || process.env.TOPOLOGY || "").trim().toLowerCase() === "vm-distributed";
}

function connectorModelServerBaseUrlFromConfig(): string {
  return (
    process.env.UI_AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL ||
    process.env.AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL ||
    process.env.UI_MODEL_SERVER_CONNECTOR_BASE_URL ||
    process.env.MODEL_SERVER_CONNECTOR_BASE_URL ||
    process.env.UI_AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_URL ||
    process.env.AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_URL ||
    process.env.UI_MODEL_SERVER_CONNECTOR_URL ||
    process.env.MODEL_SERVER_CONNECTOR_URL ||
    ""
  ).trim();
}

function connectorModelServerBaseUrlFromTopology(): string {
  if (!isVmDistributedTopology()) {
    return "";
  }

  const publicPath = (
    process.env.UI_AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH ||
    process.env.AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH ||
    "/model-server"
  ).trim();
  const commonHttpUrl = (
    process.env.UI_VM_COMMON_HTTP_URL ||
    process.env.VM_COMMON_HTTP_URL ||
    process.env.UI_VM_COMMON_PUBLIC_URL ||
    process.env.VM_COMMON_PUBLIC_URL ||
    ""
  ).trim();
  const commonBaseUrl = forceUrlScheme(commonHttpUrl, "http");
  if (commonBaseUrl) {
    return appendUrlPath(commonBaseUrl, publicPath);
  }

  const domain = (
    process.env.UI_DS_DOMAIN ||
    process.env.DS_DOMAIN_BASE ||
    process.env.DS_DOMAIN ||
    process.env.DOMAIN_BASE ||
    ""
  ).trim();
  if (!domain) {
    return "";
  }
  return appendUrlPath(`http://org1.${domain}`, publicPath);
}

function publicModelServerBaseUrlFromTopology(): string {
  if (!isVmDistributedTopology()) {
    return "";
  }

  const explicitHost = (
    process.env.UI_AI_MODEL_HUB_MODEL_SERVER_PUBLIC_HOST ||
    process.env.AI_MODEL_HUB_MODEL_SERVER_PUBLIC_HOST ||
    process.env.UI_COMPONENTS_PUBLIC_HOST ||
    process.env.COMPONENTS_PUBLIC_HOST ||
    ""
  ).trim();
  const domain = (
    process.env.UI_DS_DOMAIN ||
    process.env.DS_DOMAIN_BASE ||
    process.env.DS_DOMAIN ||
    process.env.DOMAIN_BASE ||
    ""
  ).trim();
  const host = explicitHost || (domain ? `org1.${domain}` : "");
  if (!host) {
    return "";
  }

  const protocol = (process.env.UI_PUBLIC_PROTOCOL || process.env.PUBLIC_PROTOCOL || "https").trim() || "https";
  const publicPath = (
    process.env.UI_AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH ||
    process.env.AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH ||
    "/model-server"
  ).trim();
  return appendUrlPath(`${protocol}://${host}`, publicPath);
}

export function modelServerUrlForPath(
  pathValue: string,
  componentsNamespace: string,
  options: { explicitUrlEnv?: string } = {},
): string {
  const explicitUrlEnv = options.explicitUrlEnv || "UI_AI_MODEL_HUB_MODEL_URL";
  const explicitUrl = (process.env[explicitUrlEnv] || "").trim();
  if (explicitUrl) {
    return explicitUrl;
  }

  const connectorBaseUrl = connectorModelServerBaseUrlFromConfig() || connectorModelServerBaseUrlFromTopology();
  if (connectorBaseUrl) {
    return appendUrlPath(connectorBaseUrl, pathValue);
  }

  const publicBaseUrl = (
    process.env.AI_MODEL_HUB_MODEL_SERVER_BASE_URL ||
    process.env.UI_AI_MODEL_HUB_MODEL_SERVER_BASE_URL ||
    ""
  ).trim();
  if (publicBaseUrl) {
    return appendUrlPath(publicBaseUrl, pathValue);
  }

  const inferredPublicBaseUrl = publicModelServerBaseUrlFromTopology();
  if (inferredPublicBaseUrl) {
    return appendUrlPath(inferredPublicBaseUrl, pathValue);
  }

  const namespace = (process.env.UI_AI_MODEL_HUB_MODEL_NAMESPACE || componentsNamespace || "components").trim();
  return `http://model-server.${namespace}.svc.cluster.local:8080${normalizePath(pathValue)}`;
}

export function modelServerBaseUrlFromUrl(fullUrl: string, pathValue: string): string {
  const trimmedUrl = withoutTrailingSlash(fullUrl.trim());
  const normalizedPath = normalizePath(pathValue);
  if (!trimmedUrl || normalizedPath === "/") {
    return trimmedUrl;
  }

  try {
    const parsed = new URL(trimmedUrl);
    if (parsed.pathname.endsWith(normalizedPath)) {
      const basePath = parsed.pathname.slice(0, -normalizedPath.length);
      parsed.pathname = basePath || "/";
      parsed.search = "";
      parsed.hash = "";
      return withoutTrailingSlash(parsed.toString());
    }
  } catch {
    if (trimmedUrl.endsWith(normalizedPath)) {
      return withoutTrailingSlash(trimmedUrl.slice(0, -normalizedPath.length));
    }
  }

  return trimmedUrl;
}

export function modelServerBaseUrlForPath(
  pathValue: string,
  componentsNamespace: string,
  options: { explicitUrlEnv?: string } = {},
): string {
  return modelServerBaseUrlFromUrl(modelServerUrlForPath(pathValue, componentsNamespace, options), pathValue);
}
