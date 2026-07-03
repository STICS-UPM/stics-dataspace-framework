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

type ConsumerAgreementArtifacts = {
  agreementId: string | null;
  assetId: string;
  attempts: number;
  agreement: unknown;
};

type ConsumerTransferArtifacts = {
  transferId: string;
  finalState: string;
  transferType: string;
  assetId: string;
};

type ConsumerTransferReadinessProbe = {
  status: "ready" | "timeout";
  assetId: string;
  agreementId: string;
  transferCount: number;
  readyTransferId?: string;
  readyState?: string;
  transfers: Array<{
    transferId: string;
    state: string;
    assetId?: string;
    contractId?: string;
    transferType?: string;
  }>;
  error?: string;
};

type ConsumerEdrProbeTransfer = {
  transferId: string;
  state: string;
  assetId?: string;
  contractId?: string;
  transferType?: string;
  edrHttpStatus?: number;
  edrEndpointPresent: boolean;
  edrAuthorizationPresent: boolean;
};

type ConsumerEdrReadinessProbe = {
  status: "ready" | "timeout";
  assetId: string;
  agreementId: string;
  transferCount: number;
  transfers: ConsumerEdrProbeTransfer[];
  error?: string;
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

type TokenProvider = string | (() => Promise<string>);

export type ProviderContractDefinitionLookup = {
  contractDefinitionId: string;
  found: boolean;
  itemCount: number;
  attempts: number;
  httpStatus?: number;
  matchedItem?: unknown;
};

const TRANSIENT_HTTP_STATUSES = new Set([401, 502, 503, 504]);
const TRANSIENT_FEDERATED_CATALOG_HTTP_STATUSES = new Set([401, 500, 502, 503, 504]);
const TRANSIENT_HTTP_MAX_ATTEMPTS = 4;
const TRANSIENT_HTTP_RETRY_DELAY_MS = 2000;
const CLEANUP_ENTITY_ORDER: CleanupEntityKind[] = ["contractdefinitions", "policydefinitions", "assets"];
const DEFAULT_CATALOG_READINESS_TIMEOUT_MS = 180_000;
const ACCEPTED_CONSUMER_TRANSFER_STATES = new Set(["STARTED", "COMPLETED", "ENDED", "TERMINATED", "DEPROVISIONED"]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isTransientHttpStatus(status: number): boolean {
  return TRANSIENT_HTTP_STATUSES.has(status);
}

function isTransientFederatedCatalogReadinessError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  const match = message.match(/Consumer federated catalog (?:request|count) failed with HTTP (\d+)/);
  if (!match) {
    return false;
  }
  return TRANSIENT_FEDERATED_CATALOG_HTTP_STATUSES.has(Number(match[1]));
}

function catalogReadinessTimeoutMs(): number {
  const configured = Number.parseInt(
    process.env.UI_CATALOG_READINESS_TIMEOUT_MS ||
      process.env.UI_FEDERATED_CATALOG_READINESS_TIMEOUT_MS ||
      "",
    10,
  );
  if (Number.isFinite(configured) && configured > 0) {
    return configured;
  }
  const topology = (
    process.env.UI_TOPOLOGY ||
    process.env.PIONERA_TOPOLOGY ||
    process.env.INESDATA_TOPOLOGY ||
    process.env.TOPOLOGY ||
    ""
  )
    .trim()
    .toLowerCase();
  if (topology === "vm-distributed") {
    return 360_000;
  }
  return DEFAULT_CATALOG_READINESS_TIMEOUT_MS;
}

async function resolveToken(tokenProvider: TokenProvider): Promise<string> {
  return typeof tokenProvider === "function" ? tokenProvider() : tokenProvider;
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

async function executeRetriableConsumerRequest<
  TResponse extends { ok(): boolean; status(): number; text(): Promise<string> },
>(
  action: string,
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  execute: (consumerToken: string) => Promise<TResponse>,
  maxAttempts = TRANSIENT_HTTP_MAX_ATTEMPTS,
): Promise<{ response: TResponse; consumerToken: string }> {
  let consumerToken = "";
  const response = await executeRetriableRequest(
    action,
    async () => {
      consumerToken = await issueConsumerToken(request, runtime);
      return execute(consumerToken);
    },
    maxAttempts,
  );
  return { response, consumerToken };
}

async function createPolicy(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  providerToken: TokenProvider,
  policyId: string,
): Promise<void> {
  await executeRetriableRequest("Create policy", async () => {
    const token = await resolveToken(providerToken);
    return request.post(`${runtime.provider.managementBaseUrl}/policydefinitions`, {
      headers: {
        Authorization: `Bearer ${token}`,
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
    });
  });
}

export async function createProviderPolicyDefinition(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  policyId: string,
): Promise<void> {
  const providerToken = () => issueUserToken(request, runtime);
  await createPolicy(request, runtime, providerToken, policyId);
}

async function createAsset(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  providerToken: TokenProvider,
  assetId: string,
  sourceObjectNameOrOptions: string | AssetBootstrapOptions = "todos",
): Promise<void> {
  const options: AssetBootstrapOptions =
    typeof sourceObjectNameOrOptions === "string"
      ? { sourceObjectName: sourceObjectNameOrOptions }
      : sourceObjectNameOrOptions;
  const sourceObjectName = options.sourceObjectName || "todos";
  const keywords = options.keywords || ["validation", "ui", "negotiation"];
  const dataAddress = {
    type: "HttpData",
    baseUrl: "https://jsonplaceholder.typicode.com/todos",
    name: sourceObjectName,
    ...(options.dataAddress || {}),
  };
  const dataAddressType =
    typeof dataAddress.type === "string" && dataAddress.type.trim().length > 0
      ? dataAddress.type.trim()
      : undefined;
  const storageMetadata = dataAddressType
    ? {
        storageType: dataAddressType,
        "edc:dataAddressType": dataAddressType,
        "https://w3id.org/edc/v0.0.1/ns/dataAddressType": dataAddressType,
      }
    : {};

  await executeRetriableRequest("Create asset", async () => {
    const token = await resolveToken(providerToken);
    return request.post(`${runtime.provider.managementBaseUrl}/assets`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
          edc: "https://w3id.org/edc/v0.0.1/ns/",
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
          ...storageMetadata,
          ...(options.properties || {}),
        },
        dataAddress,
      },
    });
  });
}

async function createContractDefinition(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  providerToken: TokenProvider,
  contractDefinitionId: string,
  policyId: string,
  assetId: string,
): Promise<void> {
  await executeRetriableRequest("Create contract definition", async () => {
    const token = await resolveToken(providerToken);
    return request.post(`${runtime.provider.managementBaseUrl}/contractdefinitions`, {
      headers: {
        Authorization: `Bearer ${token}`,
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
    });
  });
}

export async function bootstrapProviderContractArtifacts(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  suffix: string,
): Promise<BootstrapArtifacts> {
  const providerToken = () => issueUserToken(request, runtime);
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
  const providerToken = () => issueUserToken(request, runtime);
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

export async function probeProviderContractDefinition(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  contractDefinitionId: string,
): Promise<ProviderContractDefinitionLookup> {
  const providerToken = await issueUserToken(request, runtime);
  const limit = 100;
  let itemCount = 0;
  let attempts = 0;
  let httpStatus: number | undefined;

  for (let offset = 0; offset < 500; offset += limit) {
    attempts += 1;
    const response = await executeRetriableRequest("Probe provider contract definition", () =>
      request.post(`${runtime.provider.managementBaseUrl}/contractdefinitions/request`, {
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
    httpStatus = response.status();
    const items = payloadItems(await response.json());
    itemCount += items.length;
    const matchedItem = items.find((item) => extractEntityId(item) === contractDefinitionId);
    if (matchedItem) {
      return {
        contractDefinitionId,
        found: true,
        itemCount,
        attempts,
        httpStatus,
        matchedItem,
      };
    }
    if (items.length < limit) {
      break;
    }
  }

  return {
    contractDefinitionId,
    found: false,
    itemCount,
    attempts,
    httpStatus,
  };
}

export async function fetchConsumerCatalogResponse(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  counterPartyAddress: string,
  counterPartyId?: string,
): Promise<unknown> {
  const { response } = await executeRetriableConsumerRequest("Consumer catalog request", request, runtime, (consumerToken) =>
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
  const { response } = await executeRetriableConsumerRequest("Consumer federated catalog request", request, runtime, (consumerToken) =>
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
  const { response } = await executeRetriableConsumerRequest("Consumer federated catalog count", request, runtime, (consumerToken) =>
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
  timeoutMs = catalogReadinessTimeoutMs(),
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
  timeoutMs = catalogReadinessTimeoutMs(),
): Promise<{ catalogResponse: any; dataset: any; datasetCount: number }> {
  const deadline = Date.now() + timeoutMs;
  let lastDatasetFound = false;
  let lastDatasetCount = 0;
  let lastTransientError = "";

  while (Date.now() < deadline) {
    try {
      const catalogResponse = await fetchConsumerFederatedCatalogResponse(request, runtime);
      lastDatasetCount = federatedCatalogDatasetCount(catalogResponse);
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
      lastTransientError = "";
    } catch (error) {
      if (!isTransientFederatedCatalogReadinessError(error)) {
        throw error;
      }
      lastTransientError = error instanceof Error ? error.message : String(error);
    }
    await sleep(2000);
  }

  throw new Error(
    `Federated catalog dataset '${assetId}' did not expose an offer policy in time. ` +
      `Last catalog state: ${lastDatasetFound ? "dataset without offer policy" : "dataset not found"}. ` +
      `Last visible dataset count: ${lastDatasetCount}` +
      (lastTransientError ? `. Last transient catalog error: ${lastTransientError}` : ""),
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
  const topology = (
    process.env.UI_TOPOLOGY ||
    process.env.PIONERA_TOPOLOGY ||
    process.env.INESDATA_TOPOLOGY ||
    process.env.TOPOLOGY ||
    ""
  )
    .trim()
    .toLowerCase();
  if (topology === "vm-distributed") {
    return 360_000;
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

function extractAgreementAssetId(agreement: any): string | undefined {
  if (!agreement || typeof agreement !== "object") {
    return undefined;
  }

  const directCandidates = [
    agreement.assetId,
    agreement["edc:assetId"],
    agreement["https://w3id.org/edc/v0.0.1/ns/assetId"],
  ];

  for (const value of directCandidates) {
    const normalized = String(value || "").trim();
    if (normalized) {
      return normalized;
    }
  }

  const assetNode = agreement.asset || agreement["edc:asset"];
  if (typeof assetNode === "string" && assetNode.trim()) {
    return assetNode.trim();
  }

  if (assetNode && typeof assetNode === "object") {
    const nestedId = String(assetNode["@id"] || assetNode.id || assetNode.assetId || "").trim();
    if (nestedId) {
      return nestedId;
    }
  }

  return undefined;
}

function agreementReferencesAssetId(agreement: any, assetId: string): boolean {
  if (extractAgreementAssetId(agreement) === assetId) {
    return true;
  }

  try {
    return JSON.stringify(agreement).includes(assetId);
  } catch {
    return false;
  }
}

export async function waitForConsumerAgreement(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  attempts = 20,
  delayMs = 1000,
): Promise<ConsumerAgreementArtifacts> {
  const pageSize = 100;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    for (let offset = 0; offset <= 500; offset += pageSize) {
      const { response } = await executeRetriableConsumerRequest(
        "Poll consumer contract agreements",
        request,
        runtime,
        (consumerToken) =>
          request.post(`${runtime.consumer.managementBaseUrl}/contractagreements/request`, {
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
              filterExpression: [],
            },
          }),
      );
      await ensureOk(response, "Poll consumer contract agreements");

      const agreements = payloadItems(await response.json());
      const matchingAgreement = agreements.find((agreement: any) => agreementReferencesAssetId(agreement, assetId));
      if (matchingAgreement) {
        return {
          assetId,
          attempts: attempt,
          agreementId: matchingAgreement["@id"] || matchingAgreement.id || null,
          agreement: matchingAgreement,
        };
      }

      if (agreements.length < pageSize) {
        break;
      }
    }

    await sleep(delayMs);
  }

  throw new Error(`Consumer agreement for asset '${assetId}' did not become visible in contractagreements/request`);
}

type NegotiationLookupResult = {
  negotiation?: any;
};

async function lookupNegotiationById(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  negotiationId: string,
): Promise<NegotiationLookupResult> {
  for (let attempt = 1; attempt <= TRANSIENT_HTTP_MAX_ATTEMPTS; attempt += 1) {
    const consumerToken = await issueConsumerToken(request, runtime);
    const response = await request.get(`${runtime.consumer.managementBaseUrl}/contractnegotiations/${negotiationId}`, {
      headers: {
        Authorization: `Bearer ${consumerToken}`,
      },
    });

    if (response.ok()) {
      return { negotiation: await response.json() };
    }

    if ([404, 405].includes(response.status())) {
      return {};
    }

    if (isTransientHttpStatus(response.status()) && attempt < TRANSIENT_HTTP_MAX_ATTEMPTS) {
      await sleep(TRANSIENT_HTTP_RETRY_DELAY_MS * attempt);
      continue;
    }

    await ensureOk(response, "Consumer negotiation direct lookup");
  }
  return {};
}

async function lookupNegotiationFromList(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  negotiationId: string,
): Promise<NegotiationLookupResult> {
  const pageSize = 100;
  for (let offset = 0; offset <= 500; offset += pageSize) {
    const { response } = await executeRetriableConsumerRequest(
      "Consumer negotiation lookup",
      request,
      runtime,
      (consumerToken) =>
        request.post(`${runtime.consumer.managementBaseUrl}/contractnegotiations/request`, {
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
        }),
    );
    await ensureOk(response, "Consumer negotiation lookup");
    const lookupBody = await response.json();
    const negotiations = Array.isArray(lookupBody) ? lookupBody : [];
    const negotiation = negotiations.find((entry: any) => negotiationMatches(entry, negotiationId));
    if (negotiation) {
      return { negotiation };
    }
    if (negotiations.length < pageSize) {
      break;
    }
  }
  return {};
}

async function lookupNegotiation(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  negotiationId: string,
): Promise<any | undefined> {
  return (
    (await lookupNegotiationById(request, runtime, negotiationId)).negotiation ||
    (await lookupNegotiationFromList(request, runtime, negotiationId)).negotiation
  );
}

export async function bootstrapConsumerNegotiation(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  counterPartyAddress: string,
  counterPartyId: string,
): Promise<ConsumerNegotiationArtifacts> {
  const { catalogResponse, dataset } = await fetchConsumerCatalogDatasetWithOffer(
    request,
    runtime,
    assetId,
    counterPartyAddress,
    counterPartyId,
  );

  const { response } = await executeRetriableConsumerRequest(
    "Consumer contract negotiation request",
    request,
    runtime,
    (consumerToken) =>
      request.post(`${runtime.consumer.managementBaseUrl}/contractnegotiations`, {
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
      }),
  );
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
    const negotiation = await lookupNegotiation(request, runtime, negotiationId);
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

  const finalNegotiation = await lookupNegotiation(request, runtime, negotiationId);
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
  objectName?: string,
): Promise<ConsumerTransferArtifacts> {
  const transferStartPath = runtime.consumer.transferStartPath || "inesdatatransferprocesses";
  const transferDestinationType = runtime.consumer.transferDestinationType || "InesDataStore";
  const isEdcAdapter = runtime.adapter === "edc" || runtime.consumer.adapter === "edc";
  const usesObjectStorageDestination = transferDestinationType.toLowerCase() !== "httpdata";
  const transferType = isEdcAdapter
    ? usesObjectStorageDestination
      ? "AmazonS3-PUSH"
      : "HttpData-PULL"
    : "AmazonS3-PUSH";
  const transferObjectName = objectName || `${assetId}.json`;

  const buildDataDestination = (): Record<string, string> => {
    if (!isEdcAdapter) {
      return { type: transferDestinationType };
    }
    if (!usesObjectStorageDestination) {
      return { type: transferDestinationType };
    }
    const destination = runtime.consumer.transferDestination;
    if (!destination) {
      throw new Error("Consumer runtime does not expose an S3 transfer destination");
    }
    return {
      type: transferDestinationType,
      bucketName: destination.bucketName,
      region: destination.region,
      objectName: transferObjectName,
      keyName: transferObjectName,
      name: transferObjectName,
      endpointOverride: destination.endpointOverride,
      accessKeyId: destination.accessKeyId,
      secretAccessKey: destination.secretAccessKey,
    };
  };
  const transferPayload = isEdcAdapter
    ? {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        "@type": "TransferRequestDto",
        connectorId: runtime.provider.connectorName,
        contractId: agreementId,
        counterPartyAddress,
        protocol: "dataspace-protocol-http",
        transferType,
        ...(usesObjectStorageDestination ? { dataDestination: buildDataDestination() } : {}),
      }
    : {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        "@type": "TransferRequest",
        assetId,
        contractId: agreementId,
        counterPartyAddress,
        protocol: "dataspace-protocol-http",
        transferType,
        dataDestination: buildDataDestination(),
      };
  const { response } = await executeRetriableConsumerRequest(
    "Consumer transfer request",
    request,
    runtime,
    (consumerToken) =>
      request.post(`${runtime.consumer.managementBaseUrl}/${transferStartPath}`, {
        headers: {
          Authorization: `Bearer ${consumerToken}`,
          "Content-Type": "application/json",
        },
        data: transferPayload,
      }),
  );
  await ensureOk(response, "Consumer transfer request");
  const body = await response.json();
  const transferId = body?.["@id"] || body?.id;
  if (!transferId) {
    throw new Error("Transfer response does not contain an identifier");
  }

  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    const { response: stateResponse } = await executeRetriableConsumerRequest(
      "Consumer transfer status lookup",
      request,
      runtime,
      (consumerToken) =>
        request.get(`${runtime.consumer.managementBaseUrl}/transferprocesses/${transferId}`, {
          headers: {
            Authorization: `Bearer ${consumerToken}`,
          },
        }),
    );
    await ensureOk(stateResponse, "Consumer transfer status lookup");
    const stateBody = await stateResponse.json();
    const state = String(stateBody?.state || "").trim().toUpperCase();
    if (state === "COMPLETED" || state === "STARTED") {
      return {
        transferId,
        finalState: state,
        transferType,
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

function transferReferencesAssetAgreement(transfer: any, assetId: string, agreementId: string): boolean {
  const serialized = JSON.stringify(transfer || {});
  return serialized.includes(assetId) && serialized.includes(agreementId);
}

function transferReferencesAsset(transfer: any, assetId: string): boolean {
  return JSON.stringify(transfer || {}).includes(assetId);
}

function transferId(transfer: any): string {
  return String(transfer?.["@id"] || transfer?.id || "").trim();
}

function transferState(transfer: any): string {
  return String(transfer?.state || transfer?.["edc:state"] || "").trim().toUpperCase();
}

function transferAssetId(transfer: any): string | undefined {
  const value = transfer?.assetId || transfer?.["edc:assetId"];
  return value === undefined || value === null ? undefined : String(value).trim();
}

function transferContractId(transfer: any): string | undefined {
  const value =
    transfer?.contractId ||
    transfer?.["edc:contractId"] ||
    transfer?.contractAgreementId ||
    transfer?.["edc:contractAgreementId"];
  return value === undefined || value === null ? undefined : String(value).trim();
}

function transferType(transfer: any): string | undefined {
  const value = transfer?.transferType || transfer?.["edc:transferType"];
  return value === undefined || value === null ? undefined : String(value).trim();
}

export async function waitForConsumerTransferReadinessForAssetAgreement(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  agreementId: string,
  timeoutMs = 180_000,
): Promise<ConsumerTransferReadinessProbe> {
  const deadline = Date.now() + timeoutMs;
  let transfers: ConsumerTransferReadinessProbe["transfers"] = [];
  let lastError: string | undefined;

  while (Date.now() < deadline) {
    try {
      const consumerToken = await issueConsumerToken(request, runtime);
      const transferResponse = await request.post(`${runtime.consumer.managementBaseUrl}/transferprocesses/request`, {
        headers: {
          Authorization: `Bearer ${consumerToken}`,
          "Content-Type": "application/json",
        },
        data: {
          "@context": {
            "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
          },
          "@type": "QuerySpec",
          offset: 0,
          limit: 300,
          filterExpression: [],
        },
      });
      await ensureOk(transferResponse, "Consumer transfer readiness lookup");
      const transferBody = await transferResponse.json();
      transfers = payloadItems(transferBody)
        .filter((transfer) =>
          agreementId
            ? transferReferencesAssetAgreement(transfer, assetId, agreementId)
            : transferReferencesAsset(transfer, assetId),
        )
        .map((transfer) => ({
          transferId: transferId(transfer),
          state: transferState(transfer),
          assetId: transferAssetId(transfer),
          contractId: transferContractId(transfer),
          transferType: transferType(transfer),
        }));

      const readyTransfer = transfers.find((transfer) => ACCEPTED_CONSUMER_TRANSFER_STATES.has(transfer.state));
      if (readyTransfer) {
        return {
          status: "ready",
          assetId,
          agreementId,
          transferCount: transfers.length,
          readyTransferId: readyTransfer.transferId,
          readyState: readyTransfer.state,
          transfers,
        };
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }

    await sleep(2000);
  }

  return {
    status: "timeout",
    assetId,
    agreementId,
    transferCount: transfers.length,
    transfers,
    error: lastError,
  };
}

export async function probeConsumerEdrReadinessForAssetAgreement(
  request: APIRequestContext,
  runtime: DataspacePortalRuntime,
  assetId: string,
  agreementId: string,
  timeoutMs = 60_000,
): Promise<ConsumerEdrReadinessProbe> {
  const deadline = Date.now() + timeoutMs;
  const transfers: ConsumerEdrProbeTransfer[] = [];
  let lastError: string | undefined;

  while (Date.now() < deadline) {
    try {
      const consumerToken = await issueConsumerToken(request, runtime);
      const transferResponse = await request.post(`${runtime.consumer.managementBaseUrl}/transferprocesses/request`, {
        headers: {
          Authorization: `Bearer ${consumerToken}`,
          "Content-Type": "application/json",
        },
        data: {
          "@context": {
            "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
          },
          offset: 0,
          limit: 200,
        },
      });
      await ensureOk(transferResponse, "Consumer transfer process EDR probe");
      const transferBody = await transferResponse.json();
      const matchingTransfers = payloadItems(transferBody).filter((transfer) =>
        transferReferencesAssetAgreement(transfer, assetId, agreementId),
      );

      transfers.splice(0, transfers.length);
      for (const transfer of matchingTransfers) {
        const id = transferId(transfer);
        const summary: ConsumerEdrProbeTransfer = {
          transferId: id,
          state: transferState(transfer),
          assetId: transferAssetId(transfer),
          contractId: transferContractId(transfer),
          transferType: transferType(transfer),
          edrEndpointPresent: false,
          edrAuthorizationPresent: false,
        };

        if (id) {
          const edrResponse = await request.get(
            `${runtime.consumer.managementBaseUrl}/edrs/${encodeURIComponent(id)}/dataaddress`,
            {
              headers: {
                Authorization: `Bearer ${consumerToken}`,
              },
            },
          );
          summary.edrHttpStatus = edrResponse.status();
          if (edrResponse.ok()) {
            const edrBody = await edrResponse.json();
            summary.edrEndpointPresent = Boolean(
              edrBody?.endpoint || edrBody?.["edc:endpoint"] || edrBody?.endpointUrl || edrBody?.["edc:endpointUrl"],
            );
            summary.edrAuthorizationPresent = Boolean(
              edrBody?.authorization || edrBody?.["edc:authorization"] || edrBody?.authCode || edrBody?.["edc:authCode"],
            );
          }
        }

        transfers.push(summary);
      }

      if (transfers.some((transfer) => transfer.edrEndpointPresent && transfer.edrAuthorizationPresent)) {
        return {
          status: "ready",
          assetId,
          agreementId,
          transferCount: transfers.length,
          transfers: [...transfers],
        };
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }

    await sleep(2_000);
  }

  return {
    status: "timeout",
    assetId,
    agreementId,
    transferCount: transfers.length,
    transfers: [...transfers],
    error: lastError,
  };
}
