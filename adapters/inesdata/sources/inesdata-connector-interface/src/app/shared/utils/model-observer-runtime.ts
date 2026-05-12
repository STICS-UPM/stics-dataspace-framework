export interface ModelObserverRuntimeConfig {
  strapiUrl?: string;
  managementApiUrl?: string;
  participantId?: string;
  oauth2?: {
    allowedUrls?: string;
  };
}

export interface BrowserLocationLike {
  protocol: string;
  hostname: string;
  origin: string;
}

const MODEL_OBSERVER_PROXY_PATH = '/inesdata-connector-interface/model-observer';

function getBrowserLocation(): BrowserLocationLike | null {
  if (typeof window === 'undefined' || !window.location) {
    return null;
  }

  return window.location;
}

function normalizeUrl(url?: string | null): string {
  const trimmed = `${url ?? ''}`.trim();
  return trimmed ? trimmed.replace(/\/+$/, '') : '';
}

function normalizeProtocol(protocol?: string | null): string {
  const trimmed = `${protocol ?? ''}`.trim();
  if (!trimmed) {
    return 'http:';
  }

  return trimmed.endsWith(':') ? trimmed : `${trimmed}:`;
}

function parseUrl(url: string): URL | null {
  try {
    return new URL(url);
  } catch {
    return null;
  }
}

function uniqueUrls(urls: string[]): string[] {
  return Array.from(new Set(urls.map((url) => normalizeUrl(url)).filter(Boolean)));
}

function splitConfiguredUrls(allowedUrls?: string | null): string[] {
  return uniqueUrls(`${allowedUrls ?? ''}`.split(','));
}

function deriveDataspaceName(participantId?: string | null, hostname?: string | null): string {
  const participant = `${participantId ?? ''}`.trim();
  if (participant) {
    const tokens = participant.split('-').filter(Boolean);
    return tokens[tokens.length - 1] || '';
  }

  const firstLabel = `${hostname ?? ''}`.trim().split('.')[0];
  const tokens = firstLabel.split('-').filter(Boolean);
  return tokens[tokens.length - 1] || '';
}

function deriveBackendHostname(hostname?: string | null, participantId?: string | null): string {
  const cleanHostname = `${hostname ?? ''}`.trim();
  if (!cleanHostname) {
    return '';
  }

  if (cleanHostname.startsWith('backend-')) {
    return cleanHostname;
  }

  const dataspace = deriveDataspaceName(participantId, cleanHostname);
  if (!dataspace) {
    return '';
  }

  const backendLabel = `backend-${dataspace}`;
  const participantPrefix = `${`${participantId ?? ''}`.trim()}.`;
  if (`${participantId ?? ''}`.trim() && cleanHostname.startsWith(participantPrefix)) {
    return cleanHostname.replace(participantPrefix, `${backendLabel}.`);
  }

  const firstLabel = cleanHostname.split('.')[0];
  if (firstLabel.startsWith('conn-')) {
    return cleanHostname.replace(`${firstLabel}.`, `${backendLabel}.`);
  }

  return '';
}

function buildOrigin(protocol: string, hostname: string): string {
  return hostname ? `${normalizeProtocol(protocol)}//${hostname}` : '';
}

function resolveModelObserverProxyBaseUrl(location: BrowserLocationLike | null): string {
  const origin = normalizeUrl(location?.origin);
  return origin ? `${origin}${MODEL_OBSERVER_PROXY_PATH}` : '';
}

function resolvePortalBackendOrigin(
  runtime: ModelObserverRuntimeConfig,
  location: BrowserLocationLike | null = getBrowserLocation()
): string {
  const configuredUrls = splitConfiguredUrls(runtime.oauth2?.allowedUrls);
  const preferredConfiguredUrl = configuredUrls.find((url) => {
    const parsed = parseUrl(url);
    return Boolean(parsed?.hostname.startsWith('backend-'));
  });
  if (preferredConfiguredUrl) {
    return preferredConfiguredUrl;
  }

  const managementUrl = parseUrl(normalizeUrl(runtime.managementApiUrl));
  const derivedFromManagement = buildOrigin(
    managementUrl?.protocol ?? location?.protocol ?? 'http:',
    deriveBackendHostname(managementUrl?.hostname, runtime.participantId)
  );
  if (derivedFromManagement) {
    return derivedFromManagement;
  }

  return buildOrigin(
    location?.protocol ?? 'http:',
    deriveBackendHostname(location?.hostname, runtime.participantId)
  );
}

export function resolveModelObserverApiBaseUrl(
  runtime: ModelObserverRuntimeConfig,
  location: BrowserLocationLike | null = getBrowserLocation()
): string {
  const proxyBaseUrl = resolveModelObserverProxyBaseUrl(location);
  if (proxyBaseUrl) {
    return proxyBaseUrl;
  }

  const directStrapiUrl = normalizeUrl(runtime.strapiUrl);
  const backendOrigin = directStrapiUrl || resolvePortalBackendOrigin(runtime, location);
  return backendOrigin ? `${backendOrigin}/api/model-observer` : '';
}

export function resolveOauthAllowedUrls(
  runtime: ModelObserverRuntimeConfig,
  location: BrowserLocationLike | null = getBrowserLocation()
): string[] {
  const configuredUrls = splitConfiguredUrls(runtime.oauth2?.allowedUrls);
  const directStrapiUrl = normalizeUrl(runtime.strapiUrl);
  const backendOrigin = resolvePortalBackendOrigin(runtime, location);

  return uniqueUrls([
    ...configuredUrls,
    directStrapiUrl,
    backendOrigin
  ]);
}