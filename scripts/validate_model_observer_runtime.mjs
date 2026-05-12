#!/usr/bin/env node

import http from 'node:http';
import https from 'node:https';

function parseArgs(argv) {
  const options = {
    baseUrl: 'http://localhost:8080',
    path: '/inesdata-connector-interface/assets/config/app.config.json',
    host: '',
    checkSummary: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];

    if (arg === '--host') {
      options.host = argv[index + 1] || '';
      index += 1;
      continue;
    }

    if (arg === '--base-url') {
      options.baseUrl = argv[index + 1] || options.baseUrl;
      index += 1;
      continue;
    }

    if (arg === '--path') {
      options.path = argv[index + 1] || options.path;
      index += 1;
      continue;
    }

    if (arg === '--check-summary') {
      options.checkSummary = true;
    }
  }

  if (!options.host) {
    throw new Error('Missing required argument --host <connector-host>.');
  }

  return options;
}

function normalizeUrl(url) {
  const trimmed = `${url || ''}`.trim();
  return trimmed ? trimmed.replace(/\/+$/, '') : '';
}

function splitConfiguredUrls(allowedUrls) {
  const urls = `${allowedUrls || ''}`
    .split(',')
    .map((url) => normalizeUrl(url))
    .filter(Boolean);

  return Array.from(new Set(urls));
}

function deriveDataspaceName(participantId, hostname) {
  const participant = `${participantId || ''}`.trim();
  if (participant) {
    const tokens = participant.split('-').filter(Boolean);
    return tokens[tokens.length - 1] || '';
  }

  const firstLabel = `${hostname || ''}`.trim().split('.')[0];
  const tokens = firstLabel.split('-').filter(Boolean);
  return tokens[tokens.length - 1] || '';
}

function deriveBackendHostname(hostname, participantId) {
  const cleanHostname = `${hostname || ''}`.trim();
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
  const participant = `${participantId || ''}`.trim();
  const participantPrefix = participant ? `${participant}.` : '';
  if (participantPrefix && cleanHostname.startsWith(participantPrefix)) {
    return cleanHostname.replace(participantPrefix, `${backendLabel}.`);
  }

  const firstLabel = cleanHostname.split('.')[0];
  if (firstLabel.startsWith('conn-')) {
    return cleanHostname.replace(`${firstLabel}.`, `${backendLabel}.`);
  }

  return '';
}

function resolvePortalBackendOrigin(config, connectorHost) {
  const configuredUrls = splitConfiguredUrls(config?.oauth2?.allowedUrls);
  const configuredBackendUrl = configuredUrls.find((url) => {
    try {
      return new URL(url).hostname.startsWith('backend-');
    } catch {
      return false;
    }
  });
  if (configuredBackendUrl) {
    return configuredBackendUrl;
  }

  const managementUrl = normalizeUrl(config?.managementApiUrl);
  if (managementUrl) {
    const parsedManagementUrl = new URL(managementUrl);
    const backendHostname = deriveBackendHostname(parsedManagementUrl.hostname, config?.participantId);
    if (backendHostname) {
      return `${parsedManagementUrl.protocol}//${backendHostname}`;
    }
  }

  const backendHostname = deriveBackendHostname(connectorHost, config?.participantId);
  return backendHostname ? `http://${backendHostname}` : '';
}

function resolveModelObserverApiBaseUrl(config, connectorHost) {
  const directStrapiUrl = normalizeUrl(config?.strapiUrl);
  const backendOrigin = directStrapiUrl || resolvePortalBackendOrigin(config, connectorHost);
  return backendOrigin ? `${backendOrigin}/api/model-observer` : '';
}

function request(url, hostHeader) {
  return new Promise((resolve, reject) => {
    const parsedUrl = new URL(url);
    const client = parsedUrl.protocol === 'https:' ? https : http;
    const req = client.request(
      parsedUrl,
      {
        method: 'GET',
        headers: hostHeader ? { Host: hostHeader } : {},
      },
      (response) => {
        let body = '';
        response.setEncoding('utf8');
        response.on('data', (chunk) => {
          body += chunk;
        });
        response.on('end', () => {
          resolve({
            status: response.statusCode || 0,
            body,
          });
        });
      }
    );

    req.on('error', reject);
    req.end();
  });
}

async function fetchJson(url, hostHeader) {
  const response = await request(url, hostHeader);
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`Request to ${url} failed with HTTP ${response.status}.`);
  }

  return JSON.parse(response.body);
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const runtimeConfigUrl = `${normalizeUrl(options.baseUrl)}${options.path}`;
  const runtimeConfig = await fetchJson(runtimeConfigUrl, options.host);
  const resolvedObserverApiBaseUrl = resolveModelObserverApiBaseUrl(runtimeConfig, options.host);
  const warnings = [];

  if (!runtimeConfig.strapiUrl) {
    warnings.push('Runtime config does not expose strapiUrl; frontend fallback resolution is required.');
  }

  const allowedUrls = splitConfiguredUrls(runtimeConfig?.oauth2?.allowedUrls);
  const resolvedObserverOrigin = normalizeUrl(resolvedObserverApiBaseUrl.replace(/\/api\/model-observer$/, ''));
  if (resolvedObserverOrigin && !allowedUrls.includes(resolvedObserverOrigin)) {
    warnings.push('Resolved observer backend origin is not explicitly present in oauth2.allowedUrls.');
  }

  const report = {
    connectorHost: options.host,
    runtimeConfigUrl,
    participantId: runtimeConfig?.participantId || null,
    explicitStrapiUrl: runtimeConfig?.strapiUrl || null,
    allowedUrls,
    resolvedObserverApiBaseUrl: resolvedObserverApiBaseUrl || null,
    warnings,
  };

  if (!resolvedObserverApiBaseUrl) {
    console.error(JSON.stringify(report, null, 2));
    process.exitCode = 2;
    return;
  }

  if (options.checkSummary && runtimeConfig?.participantId) {
    const summaryUrl = `${resolvedObserverApiBaseUrl}/participants/${encodeURIComponent(runtimeConfig.participantId)}/summary`;
    const parsedSummaryUrl = new URL(summaryUrl);
    const summaryTransportUrl = `${normalizeUrl(options.baseUrl)}${parsedSummaryUrl.pathname}`;
    const response = await request(summaryTransportUrl, parsedSummaryUrl.hostname);

    report.summaryCheck = {
      url: summaryUrl,
      transportUrl: summaryTransportUrl,
      httpStatus: response.status,
    };
  }

  console.log(JSON.stringify(report, null, 2));
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});