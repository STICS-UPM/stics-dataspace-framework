const { requestConnectorManagementToken } = require("./auth");

async function ensureOk(response, action) {
  if (response.ok()) {
    return;
  }

  const body = await response.text();
  throw new Error(`${action} failed with HTTP ${response.status()}: ${body.slice(0, 500)}`);
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

  const assetResponse = await request.post(`${runtime.providerManagementUrl}/v3/assets`, {
    headers: {
      Authorization: `Bearer ${providerToken}`,
      "Content-Type": "application/json",
    },
    data: {
      "@context": {
        "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        dct: "http://purl.org/dc/terms/",
        dcat: "http://www.w3.org/ns/dcat#",
        daimo: "https://pionera.ai/edc/daimo#",
      },
      "@id": assetId,
      "@type": "Asset",
      properties: {
        name: assetName,
        version,
        shortDescription: description,
        assetType: "machineLearning",
        contenttype: runtime.modelContentType,
        "dct:description": description,
        "dcat:keyword": ["pt5-mh-03", "playwright", "publication"],
        "daimo:pipeline_tag": task,
        "daimo:library_name": library,
        "daimo:tags": ["pt5-mh-03", "playwright", "publication"],
      },
      dataAddress: {
        type: "HttpData",
        baseUrl,
        name: "published-model",
      },
    },
  });
  await ensureOk(assetResponse, "Create provider model asset");

  const policyResponse = await request.post(`${runtime.providerManagementUrl}/v3/policydefinitions`, {
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
  });
  await ensureOk(policyResponse, "Create provider publication policy");

  const contractDefinitionResponse = await request.post(
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
  );
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

  const assetResponse = await request.post(`${runtime.consumerManagementUrl}/v3/assets`, {
    headers: {
      Authorization: `Bearer ${consumerToken}`,
      "Content-Type": "application/json",
    },
    data: {
      "@context": {
        "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        dct: "http://purl.org/dc/terms/",
        dcat: "http://www.w3.org/ns/dcat#",
        daimo: "https://pionera.ai/edc/daimo#",
      },
      "@id": assetId,
      "@type": "Asset",
      properties: {
        name: assetName,
        version,
        shortDescription: description,
        assetType: "machineLearning",
        contenttype: runtime.modelContentType,
        "dct:description": description,
        "dcat:keyword": keywords,
        "daimo:pipeline_tag": task,
        "daimo:library_name": library,
        "daimo:tags": keywords,
        ...extraProperties,
      },
      dataAddress: {
        type: "HttpData",
        baseUrl,
        name: "consumer-local-model",
        ...dataAddress,
      },
    },
  });
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
    const response = await request.post(`${runtime.consumerManagementUrl}/v3/assets/request`, {
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
    });
    await ensureOk(response, "Poll consumer local assets");

    const body = await response.json();
    const serialized = JSON.stringify(body);
    if (serialized.includes(assetId)) {
      return {
        assetId,
        attempts: attempt,
      };
    }

    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }

  throw new Error(`Local consumer asset '${assetId}' did not become visible in management assets request`);
}

async function waitForLocalProviderAsset(request, runtime, assetId, attempts = 10, delayMs = 1000) {
  const providerToken = await requestConnectorManagementToken(runtime, runtime.providerConnectorId);

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const response = await request.post(`${runtime.providerManagementUrl}/v3/assets/request`, {
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
    });
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

    await new Promise((resolve) => setTimeout(resolve, delayMs));
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

async function waitForConsumerAgreement(request, runtime, assetId, attempts = 15, delayMs = 1000) {
  const consumerToken = await requestConnectorManagementToken(runtime, runtime.consumerConnectorId);

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const response = await request.post(`${runtime.consumerManagementUrl}/v3/contractagreements/request`, {
      headers: {
        Authorization: `Bearer ${consumerToken}`,
        "Content-Type": "application/json",
      },
      data: {
        "@context": {
          "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
        },
        filterExpression: [],
      },
    });
    await ensureOk(response, "Poll consumer contract agreements");

    const agreements = await response.json();
    const normalized = Array.isArray(agreements) ? agreements : [];
    const matchingAgreement = normalized.find((agreement) => extractAgreementAssetId(agreement) === assetId);
    if (matchingAgreement) {
      return {
        assetId,
        attempts: attempt,
        agreementId: matchingAgreement["@id"] || matchingAgreement.id || null,
        agreement: matchingAgreement,
      };
    }

    await new Promise((resolve) => setTimeout(resolve, delayMs));
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
    const response = await request.post(`${runtime.consumerManagementUrl}/v3/catalog/request`, {
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
    });
    await ensureOk(response, "Poll consumer catalog request");

    const body = await response.text();
    if (body.includes(assetId)) {
      return {
        assetId,
        attempts: attempt,
        counterPartyAddress,
      };
    }

    await new Promise((resolve) => setTimeout(resolve, delayMs));
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
