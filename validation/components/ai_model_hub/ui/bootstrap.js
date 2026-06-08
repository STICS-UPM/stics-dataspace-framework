const { requestConnectorManagementToken } = require("./auth");

const RETRYABLE_STATUS_CODES = new Set([502, 503, 504]);
const EDC_NAMESPACE = "https://w3id.org/edc/v0.0.1/ns/";
const DAIMO_NAMESPACE = "https://w3id.org/daimo/0.0.1/ns#";
const LEGACY_DAIMO_NAMESPACE = "https://pionera.ai/edc/daimo#";

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestWithRetry(action, requestFactory, attempts = 5, delayMs = 1000) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const response = await requestFactory();
    if (!RETRYABLE_STATUS_CODES.has(response.status()) || attempt >= attempts) {
      return response;
    }
    await delay(delayMs);
  }

  throw new Error(`${action} did not produce a response`);
}

async function ensureOk(response, action) {
  if (response.ok()) {
    return;
  }

  const body = await response.text();
  throw new Error(`${action} failed with HTTP ${response.status()}: ${body.slice(0, 500)}`);
}

function edcAssetContext() {
  return {
    "@vocab": EDC_NAMESPACE,
    edc: EDC_NAMESPACE,
    dct: "http://purl.org/dc/terms/",
    dcat: "http://www.w3.org/ns/dcat#",
    daimo: DAIMO_NAMESPACE,
  };
}

function edcStorageMetadata(dataAddressType = "HttpData") {
  return {
    storageType: dataAddressType,
    "edc:dataAddressType": dataAddressType,
    [`${EDC_NAMESPACE}dataAddressType`]: dataAddressType,
  };
}

function aiModelMetadataAliases({ task, library, inferencePath, keywords }) {
  return {
    "daimo:asset_kind": "model",
    [`${DAIMO_NAMESPACE}asset_kind`]: "model",
    [`${LEGACY_DAIMO_NAMESPACE}asset_kind`]: "model",
    "daimo:task": task,
    [`${DAIMO_NAMESPACE}task`]: task,
    [`${LEGACY_DAIMO_NAMESPACE}task`]: task,
    "daimo:pipeline_tag": task,
    [`${LEGACY_DAIMO_NAMESPACE}pipeline_tag`]: task,
    "daimo:library": library,
    "daimo:library_name": library,
    [`${DAIMO_NAMESPACE}library`]: library,
    [`${LEGACY_DAIMO_NAMESPACE}library`]: library,
    [`${LEGACY_DAIMO_NAMESPACE}library_name`]: library,
    "daimo:tags": keywords,
    [`${LEGACY_DAIMO_NAMESPACE}tags`]: keywords,
    ...(inferencePath ? {
      "daimo:inference_path": inferencePath,
      [`${DAIMO_NAMESPACE}inference_path`]: inferencePath,
      [`${LEGACY_DAIMO_NAMESPACE}inference_path`]: inferencePath,
    } : {}),
  };
}

async function createPublishedProviderModelAsset(request, runtime, payload) {
  const providerToken = await requestConnectorManagementToken(runtime, runtime.providerConnectorId);
  const {
    assetId,
    assetName,
    policyId,
    contractDefinitionId,
    baseUrl,
    description,
    version,
    task,
    library,
  } = payload;

  const assetResponse = await requestWithRetry("Create provider model asset", () => request.post(`${runtime.providerManagementUrl}/v3/assets`, {
    headers: {
      Authorization: `Bearer ${providerToken}`,
      "Content-Type": "application/json",
    },
    data: {
      "@context": edcAssetContext(),
      "@id": assetId,
      "@type": "Asset",
      properties: {
        name: assetName,
        version,
        shortDescription: description,
        assetType: "machineLearning",
        assetData: {},
        "asset:prop:type": "machineLearning",
        contenttype: runtime.modelContentType,
        "dct:description": description,
        "dcat:keyword": ["pt5-mh-03", "playwright", "publication"],
        ...edcStorageMetadata("HttpData"),
        ...aiModelMetadataAliases({
          task,
          library,
          inferencePath: payload.inferencePath || payload.modelPath,
          keywords: ["pt5-mh-03", "playwright", "publication"],
        }),
      },
      dataAddress: {
        type: "HttpData",
        baseUrl,
        method: "POST",
        name: "published-model",
        proxyPath: "true",
      },
    },
  }));
  await ensureOk(assetResponse, "Create provider model asset");

  const policyResponse = await requestWithRetry("Create provider publication policy", () => request.post(`${runtime.providerManagementUrl}/v3/policydefinitions`, {
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
  }));
  await ensureOk(policyResponse, "Create provider publication policy");

  const contractDefinitionResponse = await requestWithRetry("Create provider contract definition", () => request.post(
    `${runtime.providerManagementUrl}/v3/contractdefinitions`,
    {
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
    },
  ));
  await ensureOk(contractDefinitionResponse, "Create provider contract definition");

  return {
    assetId,
    assetName,
    policyId,
    contractDefinitionId,
    baseUrl,
    description,
    version,
    task,
    library,
  };
}

async function createLocalConsumerModelAsset(request, runtime, payload) {
  const consumerToken = await requestConnectorManagementToken(runtime, runtime.consumerConnectorId);
  const {
    assetId,
    assetName,
    baseUrl,
    description,
    version,
    task,
    library,
    keywords = [],
    extraProperties = {},
    dataAddress = {},
  } = payload;

  const assetResponse = await requestWithRetry("Create consumer local model asset", () => request.post(`${runtime.consumerManagementUrl}/v3/assets`, {
    headers: {
      Authorization: `Bearer ${consumerToken}`,
      "Content-Type": "application/json",
    },
    data: {
      "@context": edcAssetContext(),
      "@id": assetId,
      "@type": "Asset",
      properties: {
        name: assetName,
        version,
        shortDescription: description,
        assetType: "machineLearning",
        assetData: {},
        "asset:prop:type": "machineLearning",
        contenttype: runtime.modelContentType,
        "dct:description": description,
        "dcat:keyword": keywords,
        ...edcStorageMetadata("HttpData"),
        ...aiModelMetadataAliases({
          task,
          library,
          inferencePath: payload.inferencePath || payload.modelPath,
          keywords,
        }),
        ...extraProperties,
      },
      dataAddress: {
        type: "HttpData",
        baseUrl,
        method: "POST",
        name: "consumer-local-model",
        proxyPath: "true",
        ...dataAddress,
      },
    },
  }));
  await ensureOk(assetResponse, "Create consumer local model asset");

  return {
    assetId,
    assetName,
    baseUrl,
    description,
    version,
    task,
    library,
    keywords,
    extraProperties,
    dataAddress,
  };
}

async function waitForLocalConsumerAsset(request, runtime, assetId, attempts = 10, delayMs = 1000) {
  const consumerToken = await requestConnectorManagementToken(runtime, runtime.consumerConnectorId);

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const response = await requestWithRetry("Poll consumer local assets", () => request.post(`${runtime.consumerManagementUrl}/v3/assets/request`, {
      headers: {
        Authorization: `Bearer ${consumerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        offset: 0,
        limit: 1000,
      },
    }));
    await ensureOk(response, "Poll consumer local assets");

    const body = await response.json();
    const serialized = JSON.stringify(body);
    if (serialized.includes(assetId)) {
      return {
        assetId,
        attempts: attempt,
      };
    }

    await delay(delayMs);
  }

  throw new Error(`Local consumer asset '${assetId}' did not become visible in management assets request`);
}

async function waitForLocalProviderAsset(request, runtime, assetId, attempts = 10, delayMs = 1000) {
  const providerToken = await requestConnectorManagementToken(runtime, runtime.providerConnectorId);

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const response = await requestWithRetry("Poll provider local assets", () => request.post(`${runtime.providerManagementUrl}/v3/assets/request`, {
      headers: {
        Authorization: `Bearer ${providerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        offset: 0,
        limit: 1000,
      },
    }));
    await ensureOk(response, "Poll provider local assets");

    const body = await response.json();
    const normalized = Array.isArray(body) ? body : [];
    const matchingAsset = normalized.find(asset => {
      if (!asset || typeof asset !== 'object') {
        return false;
      }
      return asset['@id'] === assetId || asset.id === assetId;
    });
    if (matchingAsset) {
      return {
        assetId,
        attempts: attempt,
        asset: matchingAsset,
      };
    }

    await delay(delayMs);
  }

  throw new Error(`Local provider asset '${assetId}' did not become visible in management assets request`);
}

function extractAgreementAssetId(agreement) {
  if (!agreement || typeof agreement !== "object") {
    return null;
  }

  const directCandidates = [
    agreement.assetId,
    agreement["edc:assetId"],
    agreement["https://w3id.org/edc/v0.0.1/ns/assetId"],
  ];

  for (const value of directCandidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }

  const assetNode = agreement.asset || agreement["edc:asset"];
  if (typeof assetNode === "string" && assetNode.trim()) {
    return assetNode.trim();
  }

  if (assetNode && typeof assetNode === "object") {
    const nestedId = assetNode["@id"] || assetNode.id || assetNode.assetId;
    if (typeof nestedId === "string" && nestedId.trim()) {
      return nestedId.trim();
    }
  }

  return null;
}

function payloadItems(payload) {
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

  return Object.keys(payload).length ? [payload] : [];
}

function agreementReferencesAssetId(agreement, assetId) {
  if (extractAgreementAssetId(agreement) === assetId) {
    return true;
  }

  try {
    return JSON.stringify(agreement).includes(assetId);
  } catch {
    return false;
  }
}

async function waitForConsumerAgreement(request, runtime, assetId, attempts = 15, delayMs = 1000) {
  const consumerToken = await requestConnectorManagementToken(runtime, runtime.consumerConnectorId);
  const pageSize = 100;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    for (let offset = 0; offset <= 500; offset += pageSize) {
      const response = await requestWithRetry("Poll consumer contract agreements", () => request.post(`${runtime.consumerManagementUrl}/v3/contractagreements/request`, {
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
      }));
      await ensureOk(response, "Poll consumer contract agreements");

      const agreements = payloadItems(await response.json());
      const matchingAgreement = agreements.find((agreement) => agreementReferencesAssetId(agreement, assetId));
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

    await delay(delayMs);
  }

  throw new Error(`Consumer agreement for asset '${assetId}' did not become visible in contract agreements request`);
}

async function waitForConsumerCatalogAsset(
  request,
  runtime,
  assetId,
  counterPartyAddress = runtime.providerProtocolUrl,
  attempts = 15,
  delayMs = 1000,
) {
  const consumerToken = await requestConnectorManagementToken(runtime, runtime.consumerConnectorId);

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const response = await requestWithRetry("Poll consumer catalog request", () => request.post(`${runtime.consumerManagementUrl}/v3/catalog/request`, {
      headers: {
        Authorization: `Bearer ${consumerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        counterPartyAddress,
        protocol: "dataspace-protocol-http",
      },
    }));
    await ensureOk(response, "Poll consumer catalog request");

    const body = await response.text();
    if (body.includes(assetId)) {
      return {
        assetId,
        attempts: attempt,
        counterPartyAddress,
      };
    }

    await delay(delayMs);
  }

  throw new Error(`Catalog asset '${assetId}' did not become visible through consumer catalog request`);
}

module.exports = {
  createLocalConsumerModelAsset,
  createPublishedProviderModelAsset,
  waitForConsumerCatalogAsset,
  waitForLocalConsumerAsset,
  waitForLocalProviderAsset,
  waitForConsumerAgreement,
};
