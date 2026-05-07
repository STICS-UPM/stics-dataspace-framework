import type { APIRequestContext } from "@playwright/test";

import type { DataspacePortalRuntime } from "./dataspace-runtime";

type BootstrapArtifacts = {
  assetId: string;
  policyId: string;
  contractDefinitionId: string;
};

type AssetBootstrapOptions = {
  sourceObjectName?: string;
  name?: string;
  version?: string;
  shortDescription?: string;
  assetType?: string;
  description?: string;
  keywords?: string[];
  properties?: Record<string, unknown>;
  dataAddress?: Record<string, unknown>;
};

type CatalogDatasetReadiness = {
  assetId: string;
  counterPartyAddress: string;
  counterPartyId: string;
  datasetId: string;
  offerId: string;
  datasetCount: number;
};

type CatalogDatasetReadinessProbe = CatalogDatasetReadiness & {
  status: "ready" | "timeout";
  error?: string;
};

type ConsumerNegotiationArtifacts = {
  negotiationId: string;
  agreementId: string;
  assetId: string;
  state?: string;
};

type ConsumerTransferArtifacts = {
  transferId: string;
  finalState: string;
  transferType: string;
  assetId: string;
};

type CleanupEntityKind = "contractdefinitions" | "policydefinitions" | "assets";

type CleanupEntityReport = {
  planned: string[];
  deleted: string[];
  errors: Array<{ id: string; status?: number; message: string }>;
};

type ProviderCleanupReport = {
  enabled: boolean;
  prefixes: {
    contractdefinitions: string[];
    policydefinitions: string[];
    assets: string[];
  };
  entities: Record<CleanupEntityKind, CleanupEntityReport>;
};

const TRANSIENT_HTTP_STATUSES = new Set([401, 502, 503, 504]);
const TRANSIENT_HTTP_MAX_ATTEMPTS = 4;
const TRANSIENT_HTTP_RETRY_DELAY_MS = 2000;
const CLEANUP_ENTITY_ORDER: CleanupEntityKind[] = ["contractdefinitions", "policydefinitions", "assets"];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isTransientHttpStatus(status: number): boolean {
  return TRANSIENT_HTTP_STATUSES.has(status);
}

function emptyCleanupEntityReport(): CleanupEntityReport {
  return {
    planned: [],
    deleted: [],
    errors: [],
  };
}

function extractEntityId(entity: any): string | undefined {
  if (!entity || typeof entity !== "object") {
    return undefined;
  }

  for (const key of ["@id", "id", "assetId", "policyId", "contractDefinitionId"]) {
    const value = entity[key];
    if (value !== undefined && value !== null && String(value).trim()) {
      return String(value).trim();
    }
  }

  const properties = entity.properties;
  if (properties && typeof properties === "object") {
    for (const key of ["id", "https://w3id.org/edc/v0.0.1/ns/id"]) {
      const value = properties[key];
      if (value !== undefined && value !== null && String(value).trim()) {
        return String(value).trim();
      }
    }
  }

  return undefined;
}

function payloadItems(payload: any): any[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (!payload || typeof payload !== "object") {
    return [];
  }

  for (const key of ["@graph", "items", "results", "data", "content"]) {
    if (Array.isArray(payload[key])) {
      return payload[key];
    }
  }

  return extractEntityId(payload) ? [payload] : [];
}

function matchesAnyPrefix(value: string, prefixes: string[]): boolean {
  return prefixes.some((prefix) => value.startsWith(prefix));
}

async function transientHttpError(action: string, response: { status(): number; text(): Promise<string> }): Promise<Error> {
  const body = await response.text().catch(() => "");
  return new Error(`${action} failed with HTTP ${response.status()}: ${body.slice(0, 500)}`);
}

async function executeRetriableRequest<TResponse extends { ok(): boolean; status(): number; text(): Promise<string> }>(
  action: string,
  execute: () => Promise<TResponse>,
  maxAttempts = TRANSIENT_HTTP_MAX_ATTEMPTS,
): Promise<TResponse> {
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const response = await execute();
    if (response.ok()) {
      return response;
    }

    if (!isTransientHttpStatus(response.status()) || attempt >= maxAttempts) {
      throw await transientHttpError(action, response);
    }

    await sleep(TRANSIENT_HTTP_RETRY_DELAY_MS * attempt);
  }

  throw new Error(`${action} failed before issuing a request`);
}

async function ensureOk(response: { ok(): boolean; status(): number; text(): Promise<string> }, action: string) {
  if (response.ok()) {
    return;
  }

  const body = await response.text();
  throw new Error(`${action} failed with HTTP ${response.status()}: ${body.slice(0, 500)}`);
}

async function listProviderEntityIds(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  providerToken: string,
  entityKind: CleanupEntityKind,
  prefixes: string[],
): Promise<string[]> {
  const ids: string[] = [];
  const seen = new Set<string>();
  const limit = 100;

  for (let offset = 0; offset < 500; offset += limit) {
    const response = await executeRetriableRequest(`List provider ${entityKind}`, () =>
      request.post(`${runtime.provider.managementBaseUrl}/${entityKind}/request`, {
        headers: {
          Authorization: `Bearer ${providerToken}`,
          "Content-Type": "application/json",
        },
        data: {
          "@context": {
            "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
          },
          "@type": "QuerySpec",
          offset,
          limit,
          filterExpression: [],
        },
      }),
    );
    const items = payloadItems(await response.json());
    for (const item of items) {
      const id = extractEntityId(item);
      if (id && !seen.has(id) && matchesAnyPrefix(id, prefixes)) {
        ids.push(id);
        seen.add(id);
      }
    }
    if (items.length < limit) {
      break;
    }
  }

  return ids;
}

async function deleteProviderEntity(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  providerToken: string,
  entityKind: CleanupEntityKind,
  entityId: string,
): Promise<{ status: "deleted" | "missing"; httpStatus: number } | { status: "error"; httpStatus: number; message: string }> {
  const response = await request.delete(
    `${runtime.provider.managementBaseUrl}/${entityKind}/${encodeURIComponent(entityId)}`,
    {
      headers: {
        Authorization: `Bearer ${providerToken}`,
      },
    },
  );

  if (response.ok()) {
    return { status: "deleted", httpStatus: response.status() };
  }
  if (response.status() === 404) {
    return { status: "missing", httpStatus: response.status() };
  }

  return {
    status: "error",
    httpStatus: response.status(),
    message: (await response.text().catch(() => "")).slice(0, 500),
  };
}

async function issueUserToken(request: APIRequestContext, runtime: DataspacePortalRuntime): Promise<string> {
  const response = await executeRetriableRequest("Provider token request", () =>
    request.post(`${runtime.keycloakUrl}/realms/${runtime.dataspace}/protocol/openid-connect/token`, {
      form: {
        grant_type: "password",
        client_id: runtime.keycloakClientId,
        username: runtime.provider.username,
        password: runtime.provider.password,
        scope: "openid profile email",
      },
    }),
  );
  const body = await response.json();
  const token = body?.access_token;
  if (!token) {
    throw new Error("Provider token response does not contain access_token");
  }
  return token;
}

async function issueConsumerToken(request: APIRequestContext, runtime: DataspacePortalRuntime): Promise<string> {
  const response = await executeRetriableRequest("Consumer token request", () =>
    request.post(`${runtime.keycloakUrl}/realms/${runtime.dataspace}/protocol/openid-connect/token`, {
      form: {
        grant_type: "password",
        client_id: runtime.keycloakClientId,
        username: runtime.consumer.username,
        password: runtime.consumer.password,
        scope: "openid profile email",
      },
    }),
  );
  const body = await response.json();
  const token = body?.access_token;
  if (!token) {
    throw new Error("Consumer token response does not contain access_token");
  }
  return token;
}

async function createPolicy(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  providerToken: string,
  policyId: string,
): Promise<void> {
  await executeRetriableRequest("Create policy", () =>
    request.post(`${runtime.provider.managementBaseUrl}/policydefinitions`, {
      headers: {
        Authorization: `Bearer ${providerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
          odrl: "http://www.w3.org/ns/odrl/2/",
        },
        "@id": policyId,
        policy: {
          "@context": "http://www.w3.org/ns/odrl.jsonld",
          "@type": "Set",
          permission: [],
          prohibition: [],
          obligation: [],
        },
      },
    }),
  );
}

async function createAsset(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  providerToken: string,
  assetId: string,
  sourceObjectNameOrOptions: string | AssetBootstrapOptions = "todos",
): Promise<void> {
  const options: AssetBootstrapOptions =
    typeof sourceObjectNameOrOptions === "string"
      ? { sourceObjectName: sourceObjectNameOrOptions }
      : sourceObjectNameOrOptions;
  const sourceObjectName = options.sourceObjectName || "todos";
  const keywords = options.keywords || ["validation", "ui", "negotiation"];

  await executeRetriableRequest("Create asset", () =>
    request.post(`${runtime.provider.managementBaseUrl}/assets`, {
      headers: {
        Authorization: `Bearer ${providerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
          dct: "http://purl.org/dc/terms/",
          dcat: "http://www.w3.org/ns/dcat#",
          daimo: "https://w3id.org/daimo/0.0.1/ns#",
        },
        "@id": assetId,
        "@type": "Asset",
        properties: {
          name: options.name || `UI Negotiation Asset ${assetId}`,
          version: options.version || "1.0.0",
          shortDescription: options.shortDescription || "Asset bootstrap for UI negotiation validation",
          assetType: options.assetType || "dataset",
          assetData: {},
          "dct:description": options.description || "Asset bootstrap for UI negotiation validation",
          "dcat:keyword": keywords,
          sourceObjectName,
          ...(options.properties || {}),
        },
        dataAddress: {
          type: "HttpData",
          baseUrl: "https://jsonplaceholder.typicode.com/todos",
          name: sourceObjectName,
          ...(options.dataAddress || {}),
        },
      },
    }),
  );
}

async function createContractDefinition(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  providerToken: string,
  contractDefinitionId: string,
  policyId: string,
  assetId: string,
): Promise<void> {
  await executeRetriableRequest("Create contract definition", () =>
    request.post(`${runtime.provider.managementBaseUrl}/contractdefinitions`, {
      headers: {
        Authorization: `Bearer ${providerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        "@id": contractDefinitionId,
        accessPolicyId: policyId,
        contractPolicyId: policyId,
        assetsSelector: [
          {
            operandLeft: "https://w3id.org/edc/v0.0.1/ns/id",
            operator: "=",
            operandRight: assetId,
          },
        ],
      },
    }),
  );
}

export async function bootstrapProviderContractArtifacts(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  suffix: string,
): Promise<BootstrapArtifacts> {
  const providerToken = await issueUserToken(request, runtime);
  const policyId = `policy-ui-${suffix}`;
  const contractDefinitionId = `contract-ui-${suffix}`;

  await createPolicy(request, runtime, providerToken, policyId);
  await createContractDefinition(
    request,
    runtime,
    providerToken,
    contractDefinitionId,
    policyId,
    assetId,
  );

  return {
    assetId,
    policyId,
    contractDefinitionId,
  };
}

export async function bootstrapProviderNegotiationArtifacts(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  suffix: string,
  sourceObjectNameOrOptions?: string | AssetBootstrapOptions,
): Promise<BootstrapArtifacts> {
  const providerToken = await issueUserToken(request, runtime);
  const policyId = `policy-ui-${suffix}`;
  const contractDefinitionId = `contract-ui-${suffix}`;

  await createAsset(request, runtime, providerToken, assetId, sourceObjectNameOrOptions);
  await createPolicy(request, runtime, providerToken, policyId);
  await createContractDefinition(
    request,
    runtime,
    providerToken,
    contractDefinitionId,
    policyId,
    assetId,
  );

  return {
    assetId,
    policyId,
    contractDefinitionId,
  };
}

export async function cleanupProviderValidationArtifacts(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  prefixes: Partial<Record<CleanupEntityKind, string[]>>,
): Promise<ProviderCleanupReport> {
  const providerToken = await issueUserToken(request, runtime);
  const normalizedPrefixes = {
    contractdefinitions: prefixes.contractdefinitions || [],
    policydefinitions: prefixes.policydefinitions || [],
    assets: prefixes.assets || [],
  };
  const report: ProviderCleanupReport = {
    enabled: true,
    prefixes: normalizedPrefixes,
    entities: {
      contractdefinitions: emptyCleanupEntityReport(),
      policydefinitions: emptyCleanupEntityReport(),
      assets: emptyCleanupEntityReport(),
    },
  };

  for (const entityKind of CLEANUP_ENTITY_ORDER) {
    const entityPrefixes = normalizedPrefixes[entityKind];
    if (entityPrefixes.length === 0) {
      continue;
    }

    const entityReport = report.entities[entityKind];
    entityReport.planned = await listProviderEntityIds(
      request,
      runtime,
      providerToken,
      entityKind,
      entityPrefixes,
    );

    for (const entityId of entityReport.planned) {
      const deleteResult = await deleteProviderEntity(
        request,
        runtime,
        providerToken,
        entityKind,
        entityId,
      );
      if (deleteResult.status === "error") {
        entityReport.errors.push({
          id: entityId,
          status: deleteResult.httpStatus,
          message: deleteResult.message,
        });
      } else {
        entityReport.deleted.push(entityId);
      }
    }
  }

  return report;
}

export async function fetchConsumerCatalogResponse(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  counterPartyAddress: string,
  counterPartyId?: string,
): Promise<unknown> {
  const consumerToken = await issueConsumerToken(request, runtime);
  const response = await executeRetriableRequest("Consumer catalog request", () =>
    request.post(`${runtime.consumer.managementBaseUrl}/catalog/request`, {
      headers: {
        Authorization: `Bearer ${consumerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        "@type": "CatalogRequest",
        counterPartyAddress,
        counterPartyId,
        protocol: "dataspace-protocol-http",
        querySpec: {
          offset: 0,
          limit: 100,
          filterExpression: [],
        },
      },
    }),
  );
  return await response.json();
}

function consumerManagementRoot(runtime: DataspacePortalRuntime): string {
  return runtime.consumer.managementBaseUrl.replace(/\/v3\/?$/, "");
}

async function fetchConsumerFederatedCatalogResponse(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  querySpec: Record<string, unknown> = {},
): Promise<unknown> {
  const consumerToken = await issueConsumerToken(request, runtime);
  const response = await executeRetriableRequest("Consumer federated catalog request", () =>
    request.post(`${consumerManagementRoot(runtime)}/federatedcatalog/request`, {
      headers: {
        Authorization: `Bearer ${consumerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        offset: 0,
        limit: 100,
        filterExpression: [],
        ...querySpec,
      },
    }),
  );

  return await response.json();
}

async function fetchConsumerFederatedCatalogCount(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  querySpec: Record<string, unknown> = {},
): Promise<number> {
  const consumerToken = await issueConsumerToken(request, runtime);
  const response = await executeRetriableRequest("Consumer federated catalog count", () =>
    request.post(`${consumerManagementRoot(runtime)}/pagination/count?type=federatedCatalog`, {
      headers: {
        Authorization: `Bearer ${consumerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        filterExpression: [],
        ...querySpec,
      },
    }),
  );

  const body = await response.json();
  return typeof body === "number" ? body : Number(body || 0);
}

function findCatalogDataset(catalogResponse: any, assetId: string): any {
  const datasets = Array.isArray(catalogResponse?.["dcat:dataset"])
    ? catalogResponse["dcat:dataset"]
    : Array.isArray(catalogResponse?.datasets)
      ? catalogResponse.datasets
      : [];
  return datasets.find((dataset: any) => dataset?.["@id"] === assetId || dataset?.id === assetId);
}

function catalogDatasetOffer(dataset: any): any {
  const offer = dataset?.["odrl:hasPolicy"] || dataset?.policy;
  return Array.isArray(offer) ? offer[0] : offer;
}

function federatedCatalogs(catalogResponse: any): any[] {
  return Array.isArray(catalogResponse) ? catalogResponse : [];
}

function federatedCatalogDatasets(catalog: any): any[] {
  const datasets = catalog?.["http://www.w3.org/ns/dcat#dataset"] || catalog?.["dcat:dataset"];
  if (Array.isArray(datasets)) {
    return datasets;
  }
  return datasets ? [datasets] : [];
}

function findFederatedCatalogDataset(catalogResponse: any, assetId: string): { catalog: any; dataset: any } | undefined {
  for (const catalog of federatedCatalogs(catalogResponse)) {
    const dataset = federatedCatalogDatasets(catalog).find(
      (entry: any) => entry?.["@id"] === assetId || entry?.id === assetId,
    );
    if (dataset) {
      return { catalog, dataset };
    }
  }
  return undefined;
}

function federatedCatalogDatasetOffer(dataset: any): any {
  const offers = dataset?.["odrl:hasPolicy"];
  const firstOffer = Array.isArray(offers) ? offers[0] : offers;
  return firstOffer?.["edc:offer"] || firstOffer?.offer || firstOffer;
}

function federatedCatalogDatasetCount(catalogResponse: any): number {
  return federatedCatalogs(catalogResponse).reduce(
    (count, catalog) => count + federatedCatalogDatasets(catalog).length,
    0,
  );
}

function resolveCatalogParticipantId(catalogResponse: any, fallback: string): string {
  const participant = catalogResponse?.["https://w3id.org/dspace/v0.8/participantId"];
  if (Array.isArray(participant) && participant.length > 0) {
    const first = participant[0];
    if (typeof first?.["@value"] === "string" && first["@value"].trim().length > 0) {
      return first["@value"].trim();
    }
  }
  return fallback;
}

function buildNegotiationPolicy(catalogResponse: any, dataset: any, fallbackParticipantId: string) {
  const offer = catalogDatasetOffer(dataset);
  if (!offer?.["@id"]) {
    throw new Error(`Catalog dataset '${dataset?.["@id"] || "unknown"}' does not expose an offer policy`);
  }

  return {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": offer["@type"] || "odrl:Offer",
    "@id": offer["@id"],
    assigner: resolveCatalogParticipantId(catalogResponse, fallbackParticipantId),
    target: dataset?.["@id"] || dataset?.id,
    permission: offer["odrl:permission"] || offer.permission || [],
    prohibition: offer["odrl:prohibition"] || offer.prohibition || [],
    obligation: offer["odrl:obligation"] || offer.obligation || [],
  };
}

async function fetchConsumerCatalogDatasetWithOffer(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  counterPartyAddress: string,
  counterPartyId: string,
  timeoutMs = 120_000,
): Promise<{ catalogResponse: any; dataset: any }> {
  const deadline = Date.now() + timeoutMs;
  let lastDatasetFound = false;

  while (Date.now() < deadline) {
    const catalogResponse = await fetchConsumerCatalogResponse(
      request,
      runtime,
      counterPartyAddress,
      counterPartyId,
    );
    const dataset = findCatalogDataset(catalogResponse, assetId);
    if (dataset) {
      lastDatasetFound = true;
      if (catalogDatasetOffer(dataset)?.["@id"]) {
        return { catalogResponse, dataset };
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }

  throw new Error(
    `Catalog dataset '${assetId}' did not expose an offer policy in time. ` +
      `Last catalog state: ${lastDatasetFound ? "dataset without offer policy" : "dataset not found"}`,
  );
}

async function fetchConsumerFederatedCatalogDatasetWithOffer(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  timeoutMs = 120_000,
): Promise<{ catalogResponse: any; dataset: any; datasetCount: number }> {
  const deadline = Date.now() + timeoutMs;
  let lastDatasetFound = false;

  while (Date.now() < deadline) {
    const catalogResponse = await fetchConsumerFederatedCatalogResponse(request, runtime);
    const match = findFederatedCatalogDataset(catalogResponse, assetId);
    if (match) {
      lastDatasetFound = true;
      if (federatedCatalogDatasetOffer(match.dataset)?.["@id"]) {
        const datasetCount = await fetchConsumerFederatedCatalogCount(request, runtime);
        if (datasetCount > 0) {
          return { catalogResponse, dataset: match.dataset, datasetCount };
        }
      }
    }
    await sleep(2000);
  }

  throw new Error(
    `Federated catalog dataset '${assetId}' did not expose an offer policy in time. ` +
      `Last catalog state: ${lastDatasetFound ? "dataset without offer policy" : "dataset not found"}`,
  );
}

export async function waitForConsumerCatalogDatasetReadiness(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  counterPartyAddress: string = runtime.provider.protocolBaseUrl,
  counterPartyId: string = runtime.provider.connectorName,
): Promise<CatalogDatasetReadiness> {
  const useFederatedCatalog = runtime.adapter === "inesdata";
  let catalogResponse: any;
  let dataset: any;
  let datasetCount = 0;
  let offer: any;

  if (useFederatedCatalog) {
    const readiness = await fetchConsumerFederatedCatalogDatasetWithOffer(request, runtime, assetId);
    catalogResponse = readiness.catalogResponse;
    dataset = readiness.dataset;
    datasetCount = readiness.datasetCount;
    offer = federatedCatalogDatasetOffer(dataset);
  } else {
    const readiness = await fetchConsumerCatalogDatasetWithOffer(
      request,
      runtime,
      assetId,
      counterPartyAddress,
      counterPartyId,
    );
    catalogResponse = readiness.catalogResponse;
    dataset = readiness.dataset;
    datasetCount = Array.isArray(catalogResponse?.["dcat:dataset"])
      ? catalogResponse["dcat:dataset"].length
      : Array.isArray(catalogResponse?.datasets)
        ? catalogResponse.datasets.length
        : 0;
    offer = catalogDatasetOffer(dataset);
  }

  return {
    assetId,
    counterPartyAddress,
    counterPartyId,
    datasetId: String(dataset?.["@id"] || dataset?.id || ""),
    offerId: String(offer?.["@id"] || ""),
    datasetCount,
  };
}

export async function probeConsumerCatalogDatasetReadiness(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  counterPartyAddress: string = runtime.provider.protocolBaseUrl,
  counterPartyId: string = runtime.provider.connectorName,
): Promise<CatalogDatasetReadinessProbe> {
  try {
    return {
      status: "ready",
      ...(await waitForConsumerCatalogDatasetReadiness(
        request,
        runtime,
        assetId,
        counterPartyAddress,
        counterPartyId,
      )),
    };
  } catch (error) {
    return {
      status: "timeout",
      assetId,
      counterPartyAddress,
      counterPartyId,
      datasetId: "",
      offerId: "",
      datasetCount: 0,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function negotiationTimeoutMs(): number {
  const configured = Number.parseInt(process.env.UI_EDC_NEGOTIATION_TIMEOUT_MS || "", 10);
  if (Number.isFinite(configured) && configured > 0) {
    return configured;
  }
  return 180_000;
}

function negotiationState(entry: any): string {
  return String(entry?.state || entry?.["edc:state"] || "").trim().toUpperCase();
}

function negotiationAgreementId(entry: any): string {
  return String(entry?.contractAgreementId || entry?.["edc:contractAgreementId"] || "").trim();
}

function negotiationErrorDetail(entry: any): string {
  return String(entry?.errorDetail || entry?.["edc:errorDetail"] || entry?.errorMessage || "").trim();
}

function negotiationMatches(entry: any, negotiationId: string): boolean {
  return entry?.["@id"] === negotiationId || entry?.id === negotiationId;
}

async function lookupNegotiationById(
  request: APIRequestContext,
  managementBaseUrl: string,
  consumerToken: string,
  negotiationId: string,
): Promise<any | undefined> {
  const response = await request.get(`${managementBaseUrl}/contractnegotiations/${negotiationId}`, {
    headers: {
      Authorization: `Bearer ${consumerToken}`,
    },
  });

  if (response.ok()) {
    return await response.json();
  }

  if ([404, 405].includes(response.status())) {
    return undefined;
  }

  await ensureOk(response, "Consumer negotiation direct lookup");
  return undefined;
}

async function lookupNegotiationFromList(
  request: APIRequestContext,
  managementBaseUrl: string,
  consumerToken: string,
  negotiationId: string,
): Promise<any | undefined> {
  const pageSize = 100;
  for (let offset = 0; offset <= 500; offset += pageSize) {
    const lookupResponse = await request.post(`${managementBaseUrl}/contractnegotiations/request`, {
      headers: {
        Authorization: `Bearer ${consumerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        offset,
        limit: pageSize,
      },
    });
    await ensureOk(lookupResponse, "Consumer negotiation lookup");
    const lookupBody = await lookupResponse.json();
    const negotiations = Array.isArray(lookupBody) ? lookupBody : [];
    const negotiation = negotiations.find((entry: any) => negotiationMatches(entry, negotiationId));
    if (negotiation) {
      return negotiation;
    }
    if (negotiations.length < pageSize) {
      break;
    }
  }
  return undefined;
}

async function lookupNegotiation(
  request: APIRequestContext,
  managementBaseUrl: string,
  consumerToken: string,
  negotiationId: string,
): Promise<any | undefined> {
  return (
    (await lookupNegotiationById(request, managementBaseUrl, consumerToken, negotiationId)) ||
    (await lookupNegotiationFromList(request, managementBaseUrl, consumerToken, negotiationId))
  );
}

export async function bootstrapConsumerNegotiation(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  counterPartyAddress: string,
  counterPartyId: string,
): Promise<ConsumerNegotiationArtifacts> {
  const consumerToken = await issueConsumerToken(request, runtime);
  const { catalogResponse, dataset } = await fetchConsumerCatalogDatasetWithOffer(
    request,
    runtime,
    assetId,
    counterPartyAddress,
    counterPartyId,
  );

  const response = await request.post(`${runtime.consumer.managementBaseUrl}/contractnegotiations`, {
    headers: {
      Authorization: `Bearer ${consumerToken}`,
      "Content-Type": "application/json",
    },
    data: {
      "@context": {
        "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
      },
      "@type": "ContractRequest",
      counterPartyAddress,
      protocol: "dataspace-protocol-http",
      policy: buildNegotiationPolicy(catalogResponse, dataset, counterPartyId),
    },
  });
  await ensureOk(response, "Consumer contract negotiation request");
  const body = await response.json();
  const negotiationId = body?.["@id"] || body?.id;
  if (!negotiationId) {
    throw new Error("Contract negotiation response does not contain an identifier");
  }

  const deadline = Date.now() + negotiationTimeoutMs();
  let lastState = "UNKNOWN";
  let lastErrorDetail = "";
  while (Date.now() < deadline) {
    const negotiation = await lookupNegotiation(
      request,
      runtime.consumer.managementBaseUrl,
      consumerToken,
      negotiationId,
    );
    lastState = negotiationState(negotiation) || lastState;
    lastErrorDetail = negotiationErrorDetail(negotiation) || lastErrorDetail;
    const agreementId = negotiationAgreementId(negotiation);
    if (agreementId) {
      return {
        negotiationId,
        agreementId,
        assetId,
        state: lastState,
      };
    }
    if (["ERROR", "TERMINATED", "DECLINED"].includes(lastState)) {
      throw new Error(
        `Contract negotiation '${negotiationId}' reached state '${lastState}' without agreementId` +
          (lastErrorDetail ? `: ${lastErrorDetail}` : ""),
      );
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }

  const finalNegotiation = await lookupNegotiation(
    request,
    runtime.consumer.managementBaseUrl,
    consumerToken,
    negotiationId,
  );
  const finalAgreementId = negotiationAgreementId(finalNegotiation);
  if (finalAgreementId) {
    return {
      negotiationId,
      agreementId: finalAgreementId,
      assetId,
      state: negotiationState(finalNegotiation) || lastState,
    };
  }

  throw new Error(
    `Contract negotiation '${negotiationId}' did not produce an agreement in time. ` +
      `Last observed state: ${negotiationState(finalNegotiation) || lastState}` +
      (negotiationErrorDetail(finalNegotiation) || lastErrorDetail
        ? `. Last error: ${negotiationErrorDetail(finalNegotiation) || lastErrorDetail}`
        : ""),
  );
}

export async function bootstrapConsumerTransfer(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  agreementId: string,
  counterPartyAddress: string,
): Promise<ConsumerTransferArtifacts> {
  const consumerToken = await issueConsumerToken(request, runtime);
  const transferStartPath = runtime.consumer.transferStartPath || "inesdatatransferprocesses";
  const transferDestinationType = runtime.consumer.transferDestinationType || "InesDataStore";
  const response = await request.post(`${runtime.consumer.managementBaseUrl}/${transferStartPath}`, {
    headers: {
      Authorization: `Bearer ${consumerToken}`,
      "Content-Type": "application/json",
    },
    data: {
      "@context": {
        "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
      },
      "@type": "TransferRequest",
      assetId,
      contractId: agreementId,
      counterPartyAddress,
      protocol: "dataspace-protocol-http",
      transferType: "AmazonS3-PUSH",
      dataDestination: {
        type: transferDestinationType,
      },
    },
  });
  await ensureOk(response, "Consumer transfer request");
  const body = await response.json();
  const transferId = body?.["@id"] || body?.id;
  if (!transferId) {
    throw new Error("Transfer response does not contain an identifier");
  }

  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    const stateResponse = await request.get(`${runtime.consumer.managementBaseUrl}/transferprocesses/${transferId}`, {
      headers: {
        Authorization: `Bearer ${consumerToken}`,
      },
    });
    await ensureOk(stateResponse, "Consumer transfer status lookup");
    const stateBody = await stateResponse.json();
    const state = String(stateBody?.state || "").trim().toUpperCase();
    if (state === "COMPLETED" || state === "STARTED") {
      return {
        transferId,
        finalState: state,
        transferType: "AmazonS3-PUSH",
        assetId,
      };
    }
    if (state === "TERMINATED" || state === "DEPROVISIONED" || state === "SUSPENDED" || state === "ERROR") {
      throw new Error(`Transfer '${transferId}' reached failure state '${state}'`);
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }

  throw new Error(`Transfer '${transferId}' did not reach an active state in time`);
}
