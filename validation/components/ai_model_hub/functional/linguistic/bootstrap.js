const fs = require("fs");
const path = require("path");

const { requestConnectorManagementToken } = require("../../ui/auth");
const {
  createLocalConsumerModelAsset,
  waitForConsumerAgreement,
  waitForConsumerCatalogAsset,
} = require("../../ui/bootstrap");

const FLARES_DATASET_DIR = path.resolve(
  __dirname,
  "../../../../../validation/datasets/sources/flares-dataset",
);
const FLARES_TRIAL_FILE = "5w1h_subtask_2_trial.json";
const FLARES_TEST_FILE = "5w1h_subtarea_2_test.json";

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function ensureFile(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Required FLARES source file is missing: ${filePath}`);
  }
}

function buildFlaresExpectedOutputs(trialSample, testSample) {
  const records = trialSample
    .filter((record) => Object.prototype.hasOwnProperty.call(record, "Reliability_Label"))
    .map((record) => ({
      Id: record.Id,
      "5W1H_Label": record["5W1H_Label"],
      expectedReliability: record.Reliability_Label,
    }));
  const classDistribution = {};
  for (const record of records) {
    const label = record.expectedReliability;
    classDistribution[label] = (classDistribution[label] || 0) + 1;
  }
  return {
    subtask2_trial_sample: {
      recordCount: records.length,
      classDistribution,
      records,
    },
    subtask2_test_sample: {
      recordCount: testSample.length,
      unlabeled: !testSample.some((record) => Object.prototype.hasOwnProperty.call(record, "Reliability_Label")),
      requiredFields: ["Id", "Text", "5W1H_Label", "Tag_Text", "Tag_Start", "Tag_End"],
      records: testSample
        .filter((record) => Object.prototype.hasOwnProperty.call(record, "Id"))
        .map((record) => ({
          Id: record.Id,
          "5W1H_Label": record["5W1H_Label"],
        })),
    },
  };
}

function buildFlaresMetadata(sourceDir) {
  return {
    datasetName: "FLARES",
    domain: "linguistic",
    language: "es",
    task: "5w1h-reliability-classification",
    version: "source-runtime",
    keywords: ["flares", "5w1h", "reliability", "linguistic", "mh-ling-01"],
    source: {
      name: "FLARES",
      repository: "https://github.com/rsepulveda911112/Flares-dataset",
      localPath: sourceDir,
      license: "Review upstream dataset terms before external publication.",
    },
    assetPublication: {
      assetId: "dataset-flares-subtask2",
      policyId: "policy-flares-subtask2",
      contractDefinitionId: "contractdef-flares-subtask2",
      storeFolder: "linguistic-flares",
      publicationMode: "on_demand",
      uploadFile: FLARES_TRIAL_FILE,
      fileName: "flares-subtask2-trial.json",
      uploadMediaType: "application/json",
      description: "FLARES source records used by the MH-LING-01 linguistic validation flow.",
    },
  };
}

function loadFlaresDataset(sourceDir = FLARES_DATASET_DIR) {
  const trialSamplePath = path.join(sourceDir, FLARES_TRIAL_FILE);
  const testSamplePath = path.join(sourceDir, FLARES_TEST_FILE);

  [trialSamplePath, testSamplePath].forEach(ensureFile);

  const subtask2TrialSample = readJson(trialSamplePath);
  const subtask2TestSample = readJson(testSamplePath);
  const expectedOutputs = buildFlaresExpectedOutputs(subtask2TrialSample, subtask2TestSample);

  return {
    sourceDir,
    metadata: buildFlaresMetadata(sourceDir),
    schema: {},
    subtask2TrialSample,
    subtask2TestSample,
    expectedOutputs,
    uploadFilePath: trialSamplePath,
  };
}

function buildFlaresBenchmarkRows(fixture) {
  return fixture.subtask2TrialSample.map((record) => ({
    record_id: record.Id,
    input: {
      text: record.Text,
      w1h_label: record["5W1H_Label"],
      tag_text: record.Tag_Text,
    },
    expected_label: record.Reliability_Label,
    annotation: {
      tag_start: record.Tag_Start,
      tag_end: record.Tag_End,
    },
  }));
}

function buildFlaresBenchmarkMapping() {
  return {
    inputPath: "input",
    expectedPath: "expected_label",
    predictionPath: "result.label",
  };
}

function buildFlaresInputSchema() {
  return {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    type: "object",
    additionalProperties: false,
    required: ["text", "w1h_label", "tag_text"],
    properties: {
      text: {
        type: "string",
        description: "Original news fragment associated to the FLARES annotation span.",
      },
      w1h_label: {
        type: "string",
        enum: ["WHO", "WHAT", "WHEN", "WHERE", "HOW", "WHY"],
        description: "5W1H dimension associated to the annotated span.",
      },
      tag_text: {
        type: "string",
        description: "Annotated text span under reliability assessment.",
      },
    },
  };
}

function buildFlaresInputFeatures() {
  return [
    {
      name: "text",
      type: "string",
      required: true,
      description: "Original text fragment.",
    },
    {
      name: "w1h_label",
      type: "string",
      required: true,
      description: "5W1H category for the annotated span.",
    },
    {
      name: "tag_text",
      type: "string",
      required: true,
      description: "Annotated span under reliability assessment.",
    },
  ];
}

function buildFlaresOutputSchema() {
  return {
    type: "object",
    required: ["result"],
    properties: {
      result: {
        type: "object",
        required: ["label"],
        properties: {
          label: {
            type: "string",
            enum: ["confiable", "semiconfiable", "no confiable"],
          },
        },
      },
    },
  };
}

async function ensureOk(response, action) {
  if (response.ok()) {
    return;
  }

  const body = await response.text();
  throw new Error(`${action} failed with HTTP ${response.status()}: ${body.slice(0, 500)}`);
}

async function findProviderAssetById(request, runtime, assetId) {
  const providerToken = await requestConnectorManagementToken(runtime, runtime.providerConnectorId);
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
  await ensureOk(response, "Query provider assets for FLARES");

  const assets = await response.json();
  const normalized = Array.isArray(assets) ? assets : [];
  return (
    normalized.find((asset) => {
      const directId = asset && (asset["@id"] || asset.id);
      return directId === assetId;
    }) || null
  );
}

function buildFlaresDatasetAssetDocument(fixture, runtime, overrides = {}) {
  const publication = fixture.metadata.assetPublication || {};
  const assetId = overrides.assetId || publication.assetId;
  const displayName = overrides.assetName || fixture.metadata.datasetName;
  const description = overrides.description || publication.description;
  const storeFolder = overrides.storeFolder || publication.storeFolder;
  const keywords = Array.from(
    new Set([
      ...(fixture.metadata.keywords || []),
      "flares",
      "mh-ling-01",
      "benchmark",
      "benchmark-dataset",
      "ground-truth",
      "dataset",
    ]),
  );
  const benchmarkRows = buildFlaresBenchmarkRows(fixture);
  const benchmarkMapping = buildFlaresBenchmarkMapping();

  return {
    "@context": {
      "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
      dct: "http://purl.org/dc/terms/",
      dcat: "http://www.w3.org/ns/dcat#",
      daimo: "https://pionera.ai/edc/daimo#",
    },
    "@id": assetId,
    "@type": "Asset",
    properties: {
      name: displayName,
      version: fixture.metadata.version,
      shortDescription: description,
      assetType: "dataset",
      contenttype: publication.uploadMediaType || runtime.modelContentType || "application/json",
      "dct:description": description,
      "dct:language": fixture.metadata.language,
      "dct:license": fixture.metadata.source && fixture.metadata.source.license,
      "dcat:keyword": keywords,
      "daimo:tags": keywords,
      "daimo:domain": fixture.metadata.domain,
      "daimo:task": fixture.metadata.task,
      "daimo:subtask": ["5w1h-reliability-classification"],
      "daimo:language": [fixture.metadata.language],
      "daimo:source_name": fixture.metadata.source && fixture.metadata.source.name,
      "daimo:benchmark_dataset": benchmarkRows,
      "daimo:benchmark_dataset_mapping": benchmarkMapping,
    },
    dataAddress: {
      type: publication.dataAddressType || "InesDataStore",
      folder: storeFolder,
    },
  };
}

function extractAssetProperties(asset) {
  if (!asset || typeof asset !== "object") {
    return {};
  }
  return asset["edc:properties"] || asset.properties || {};
}

function providerAssetSupportsBenchmarkMetadata(asset) {
  const properties = extractAssetProperties(asset);
  const tags = properties["daimo:tags"] || properties["https://pionera.ai/edc/daimo#tags"] || [];
  const normalizedTags = Array.isArray(tags) ? tags.map((value) => String(value).toLowerCase()) : [String(tags).toLowerCase()];
  const benchmarkDataset =
    properties["daimo:benchmark_dataset"] || properties["https://pionera.ai/edc/daimo#benchmark_dataset"];
  const benchmarkMapping =
    properties["daimo:benchmark_dataset_mapping"] ||
    properties["https://pionera.ai/edc/daimo#benchmark_dataset_mapping"];

  return (
    benchmarkDataset !== undefined &&
    benchmarkMapping !== undefined &&
    normalizedTags.some((tag) => tag.includes("dataset")) &&
    normalizedTags.some((tag) => tag.includes("benchmark"))
  );
}

function consumerAssetSupportsBenchmarkMetadata(asset) {
  return providerAssetSupportsBenchmarkMetadata(asset);
}

async function deleteProviderResource(request, runtime, resourcePath, action) {
  const providerToken = await requestConnectorManagementToken(runtime, runtime.providerConnectorId);
  const response = await request.delete(`${runtime.providerManagementUrl}${resourcePath}`, {
    headers: {
      Authorization: `Bearer ${providerToken}`,
    },
  });

  if (response.status() === 200 || response.status() === 204 || response.status() === 404) {
    return;
  }

  const body = await response.text();
  throw new Error(`${action} failed with HTTP ${response.status()}: ${body.slice(0, 500)}`);
}

async function repairFlaresDatasetPublishedAsset(request, runtime, fixture, overrides = {}) {
  const publication = fixture.metadata.assetPublication || {};
  const policyId = overrides.policyId || publication.policyId;
  const contractDefinitionId = overrides.contractDefinitionId || publication.contractDefinitionId;
  const assetId = overrides.assetId || publication.assetId;
  await deleteProviderResource(
    request,
    runtime,
    `/v3/contractdefinitions/${encodeURIComponent(contractDefinitionId)}`,
    "Delete stale FLARES contract definition",
  );
  await deleteProviderResource(
    request,
    runtime,
    `/v3/policydefinitions/${encodeURIComponent(policyId)}`,
    "Delete stale FLARES policy definition",
  );
  await deleteProviderResource(
    request,
    runtime,
    `/v3/assets/${encodeURIComponent(assetId)}`,
    "Delete stale FLARES asset",
  );
}

function buildBenchmarkReadyPublicationOverrides(fixture) {
  const publication = fixture.metadata.assetPublication || {};
  return {
    assetId: `${publication.assetId}-benchmark`,
    assetName: `${fixture.metadata.datasetName} Benchmark`,
    description:
      "Benchmark-ready FLARES provider dataset prepared for MH-LING-01 with inline rows and mapping metadata.",
    policyId: `${publication.policyId}-benchmark`,
    contractDefinitionId: `${publication.contractDefinitionId}-benchmark`,
  };
}

async function findConsumerAssetById(request, runtime, assetId) {
  const consumerToken = await requestConnectorManagementToken(runtime, runtime.consumerConnectorId);
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
  await ensureOk(response, "Query consumer assets for FLARES linguistic models");

  const assets = await response.json();
  const normalized = Array.isArray(assets) ? assets : [];
  return (
    normalized.find((asset) => {
      const directId = asset && (asset["@id"] || asset.id);
      return directId === assetId;
    }) || null
  );
}

async function deleteConsumerResource(request, runtime, resourcePath, action) {
  const consumerToken = await requestConnectorManagementToken(runtime, runtime.consumerConnectorId);
  const response = await request.delete(`${runtime.consumerManagementUrl}${resourcePath}`, {
    headers: {
      Authorization: `Bearer ${consumerToken}`,
    },
  });

  if (response.status() === 200 || response.status() === 204 || response.status() === 404) {
    return;
  }

  const body = await response.text();
  throw new Error(`${action} failed with HTTP ${response.status()}: ${body.slice(0, 500)}`);
}

function buildLocalFlaresBenchmarkDatasetDocument(fixture, runtime) {
  const benchmarkRows = buildFlaresBenchmarkRows(fixture);
  const benchmarkMapping = buildFlaresBenchmarkMapping();
  const assetId = "dataset-flares-local-benchmark";
  const keywords = [
    "flares",
    "dataset",
    "benchmark",
    "benchmark-dataset",
    "ground-truth",
    "linguistic",
    "mh-ling-01",
  ];

  return {
    assetId,
    assetName: "FLARES Local Benchmark Dataset",
    baseUrl: `${runtime.consumerDefaultUrl}/datasets/${assetId}`,
    description:
      "Local consumer-side FLARES benchmark mirror used to exercise Model Benchmarking while the provider dataset stays focused on negotiation.",
    version: fixture.metadata.version,
    task: fixture.metadata.task,
    library: "flares-dataset",
    keywords,
    extraProperties: {
      assetType: "dataset",
      "daimo:tags": keywords,
      "daimo:task": fixture.metadata.task,
      "daimo:subtask": ["5w1h-reliability-classification"],
      "daimo:language": [fixture.metadata.language],
      "daimo:benchmark_dataset": benchmarkRows,
      "daimo:benchmark_dataset_mapping": benchmarkMapping,
    },
  };
}

async function ensureLocalFlaresBenchmarkDatasetPublished(request, runtime, fixture = loadFlaresDataset()) {
  const assetDocument = buildLocalFlaresBenchmarkDatasetDocument(fixture, runtime);
  const existingAsset = await findConsumerAssetById(request, runtime, assetDocument.assetId);

  if (existingAsset) {
    if (!consumerAssetSupportsBenchmarkMetadata(existingAsset)) {
      await deleteConsumerResource(
        request,
        runtime,
        `/v3/assets/${encodeURIComponent(assetDocument.assetId)}`,
        "Delete stale local FLARES benchmark dataset",
      );
    } else {
      return {
        ...assetDocument,
        existing: true,
        created: false,
      };
    }
  }

  await createLocalConsumerModelAsset(request, runtime, assetDocument);
  return {
    ...assetDocument,
    existing: false,
    created: true,
  };
}

function buildFlaresLinguisticModelPayload(fixture, runtime, spec) {
  const benchmarkRows = buildFlaresBenchmarkRows(fixture);
  const inputExample = benchmarkRows[0] ? benchmarkRows[0].input : {};
  const outputExample = {
    result: {
      label: fixture.expectedOutputs.subtask2_trial_sample.records[0].expectedReliability,
    },
  };
  const inputSchema = buildFlaresInputSchema();
  const inputFeatures = buildFlaresInputFeatures();
  const outputSchema = buildFlaresOutputSchema();

  return {
    assetId: spec.assetId,
    assetName: spec.assetName,
    baseUrl: spec.baseUrl || `${runtime.consumerDefaultUrl}/mock-models/${spec.assetId}`,
    description: spec.description,
    version: spec.version || runtime.modelVersion,
    task: "text-classification",
    library: spec.library,
    keywords: [
      "flares",
      "linguistic",
      "inference",
      "endpoint",
      "benchmark",
      "classification",
      "mh-ling-01",
      spec.variant,
    ],
    extraProperties: {
      "daimo:task": ["nlp", "text-classification", "reliability-classification"],
      "daimo:subtask": ["5w1h-reliability-classification"],
      "daimo:language": ["es"],
      "daimo:framework": ["flares"],
      "daimo:inference_path": "/infer",
      "daimo:input_schema": JSON.stringify(inputSchema),
      "daimo:input_schema_draft": "https://json-schema.org/draft/2020-12/schema",
      "daimo:input_features": JSON.stringify(inputFeatures),
      "daimo:input_example": JSON.stringify(inputExample),
      "daimo:output_schema": JSON.stringify(outputSchema),
      "daimo:output_example": JSON.stringify(outputExample),
    },
  };
}

async function ensureFlaresLinguisticModelsPublished(request, runtime, fixture = loadFlaresDataset()) {
  const modelSpecs = [
    {
      assetId: "model-flares-reliability-baseline-a",
      assetName: "FLARES Reliability Baseline A",
      description:
        "Local linguistic baseline prepared for MH-LING-01. It exposes FLARES-compatible input metadata for benchmark readiness checks.",
      library: "flares-baseline-a",
      variant: "baseline-a",
    },
    {
      assetId: "model-flares-reliability-baseline-b",
      assetName: "FLARES Reliability Baseline B",
      description:
        "Second local linguistic baseline prepared for MH-LING-01. It shares the same FLARES-compatible input contract for comparison readiness.",
      library: "flares-baseline-b",
      variant: "baseline-b",
    },
  ];

  const results = [];

  for (const spec of modelSpecs) {
    const existingAsset = await findConsumerAssetById(request, runtime, spec.assetId);
    if (existingAsset) {
      results.push({
        ...spec,
        existing: true,
        created: false,
      });
      continue;
    }

    const payload = buildFlaresLinguisticModelPayload(fixture, runtime, spec);
    await createLocalConsumerModelAsset(request, runtime, payload);
    results.push({
      ...spec,
      existing: false,
      created: true,
    });
  }

  return {
    models: results,
    inputSchema: buildFlaresInputSchema(),
    inputFeatures: buildFlaresInputFeatures(),
    benchmarkMapping: buildFlaresBenchmarkMapping(),
    benchmarkRows: buildFlaresBenchmarkRows(fixture),
  };
}

async function probeConsumerInferEndpoint(request, runtime) {
  const response = await request.post(`${runtime.consumerDefaultUrl}/infer`, {
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    data: {
      assetId: "probe-non-existent-asset",
      payload: {},
    },
  });

  const body = await response.text();
  return {
    url: `${runtime.consumerDefaultUrl}/infer`,
    status: response.status(),
    ok: response.ok(),
    bodySnippet: body.slice(0, 500),
  };
}

async function uploadFlaresDatasetToProvider(request, runtime, fixture, assetDocument) {
  const providerToken = await requestConnectorManagementToken(runtime, runtime.providerConnectorId);
  const publication = fixture.metadata.assetPublication || {};
  const uploadFilePath = fixture.uploadFilePath;
  const uploadFileName = publication.fileName || path.basename(uploadFilePath);
  const uploadMediaType = publication.uploadMediaType || "application/json";

  ensureFile(uploadFilePath);
  const fileBuffer = fs.readFileSync(uploadFilePath);
  const jsonBuffer = Buffer.from(JSON.stringify(assetDocument, null, 2), "utf8");

  const uploadResponse = await request.post(`${runtime.providerManagementUrl}/s3assets/upload-chunk`, {
    headers: {
      Authorization: `Bearer ${providerToken}`,
      "Chunk-Index": "0",
      "Total-Chunks": "1",
      "Content-Disposition": `attachment; filename="${uploadFileName}"`,
    },
    multipart: {
      json: {
        name: `${assetDocument["@id"]}.json`,
        mimeType: "application/json",
        buffer: jsonBuffer,
      },
      file: {
        name: uploadFileName,
        mimeType: uploadMediaType,
        buffer: fileBuffer,
      },
    },
  });
  await ensureOk(uploadResponse, "Upload FLARES chunk");

  const finalizeResponse = await request.post(`${runtime.providerManagementUrl}/s3assets/finalize-upload`, {
    headers: {
      Authorization: `Bearer ${providerToken}`,
    },
    multipart: {
      json: {
        name: `${assetDocument["@id"]}.json`,
        mimeType: "application/json",
        buffer: jsonBuffer,
      },
      fileName: uploadFileName,
    },
  });
  await ensureOk(finalizeResponse, "Finalize FLARES upload");

  return {
    uploadFileName,
    uploadedBytes: fileBuffer.length,
  };
}

async function ensureProviderPolicyAndContract(request, runtime, fixture, assetDocument, overrides = {}) {
  const providerToken = await requestConnectorManagementToken(runtime, runtime.providerConnectorId);
  const publication = fixture.metadata.assetPublication || {};
  const policyId = overrides.policyId || publication.policyId;
  const contractDefinitionId = overrides.contractDefinitionId || publication.contractDefinitionId;

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
  await ensureOk(policyResponse, "Create FLARES policy definition");

  const contractDefinitionResponse = await request.post(`${runtime.providerManagementUrl}/v3/contractdefinitions`, {
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
          operandRight: assetDocument["@id"],
        },
      ],
    },
  });
  await ensureOk(contractDefinitionResponse, "Create FLARES contract definition");

  return {
    policyId,
    contractDefinitionId,
  };
}

async function ensureFlaresDatasetPublished(request, runtime, overrides = {}) {
  const fixture = loadFlaresDataset();
  const publication = fixture.metadata.assetPublication || {};
  const assetId = overrides.assetId || publication.assetId;
  const existingAsset = await findProviderAssetById(request, runtime, assetId);
  if (existingAsset) {
    if (providerAssetSupportsBenchmarkMetadata(existingAsset)) {
      return {
        fixture,
        assetId,
        existing: true,
        created: false,
        repaired: false,
        publicationMode: publication.publicationMode,
        policyId: overrides.policyId || publication.policyId,
        contractDefinitionId: overrides.contractDefinitionId || publication.contractDefinitionId,
      };
    }

    const benchmarkOverrides = {
      ...buildBenchmarkReadyPublicationOverrides(fixture),
      ...overrides,
    };
    const benchmarkAsset = await findProviderAssetById(request, runtime, benchmarkOverrides.assetId);
    if (benchmarkAsset) {
      if (!providerAssetSupportsBenchmarkMetadata(benchmarkAsset)) {
        await repairFlaresDatasetPublishedAsset(request, runtime, fixture, benchmarkOverrides);
      } else {
        return {
          fixture,
          assetId: benchmarkOverrides.assetId,
          existing: true,
          created: false,
          repaired: false,
          aliasedFrom: assetId,
          publicationMode: publication.publicationMode,
          policyId: benchmarkOverrides.policyId,
          contractDefinitionId: benchmarkOverrides.contractDefinitionId,
        };
      }
    }

    const benchmarkAssetDocument = buildFlaresDatasetAssetDocument(fixture, runtime, benchmarkOverrides);
    const uploadResult = await uploadFlaresDatasetToProvider(request, runtime, fixture, benchmarkAssetDocument);
    const contractResources = await ensureProviderPolicyAndContract(
      request,
      runtime,
      fixture,
      benchmarkAssetDocument,
      benchmarkOverrides,
    );

    return {
      fixture,
      assetId: benchmarkAssetDocument["@id"],
      existing: false,
      repaired: !!benchmarkAsset,
      created: true,
      aliasedFrom: assetId,
      publicationMode: publication.publicationMode,
      uploadResult,
      ...contractResources,
    };
  }

  const assetDocument = buildFlaresDatasetAssetDocument(fixture, runtime, overrides);
  const uploadResult = await uploadFlaresDatasetToProvider(request, runtime, fixture, assetDocument);
  const contractResources = await ensureProviderPolicyAndContract(request, runtime, fixture, assetDocument, overrides);

  return {
    fixture,
    assetId: assetDocument["@id"],
    existing: false,
    repaired: !!existingAsset,
    created: true,
    publicationMode: publication.publicationMode,
    uploadResult,
    ...contractResources,
  };
}

async function waitForFlaresDatasetCatalogVisibility(request, runtime, fixtureOrAssetId, attempts = 15, delayMs = 1000) {
  const assetId =
    typeof fixtureOrAssetId === "string"
      ? fixtureOrAssetId
      : fixtureOrAssetId?.metadata?.assetPublication?.assetId || fixtureOrAssetId?.assetId;
  if (!assetId) {
    throw new Error("FLARES asset id could not be resolved for catalog visibility polling");
  }

  return waitForConsumerCatalogAsset(request, runtime, assetId, runtime.providerProtocolUrl, attempts, delayMs);
}

async function waitForFlaresDatasetAgreement(request, runtime, fixtureOrAssetId, attempts = 20, delayMs = 1000) {
  const assetId =
    typeof fixtureOrAssetId === "string"
      ? fixtureOrAssetId
      : fixtureOrAssetId?.metadata?.assetPublication?.assetId || fixtureOrAssetId?.assetId;
  if (!assetId) {
    throw new Error("FLARES asset id could not be resolved for agreement polling");
  }

  return waitForConsumerAgreement(request, runtime, assetId, attempts, delayMs);
}

module.exports = {
  FLARES_DATASET_DIR,
  buildFlaresBenchmarkMapping,
  buildFlaresBenchmarkRows,
  buildFlaresDatasetAssetDocument,
  ensureFlaresDatasetPublished,
  ensureFlaresLinguisticModelsPublished,
  ensureLocalFlaresBenchmarkDatasetPublished,
  findConsumerAssetById,
  findProviderAssetById,
  loadFlaresDataset,
  probeConsumerInferEndpoint,
  waitForFlaresDatasetAgreement,
  waitForFlaresDatasetCatalogVisibility,
};
