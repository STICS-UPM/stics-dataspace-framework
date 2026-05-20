const { test, expect } = require("../fixtures");
const { attachManagementAuthorizationRoutes } = require("../auth");
const { waitForLocalProviderAsset } = require("../bootstrap");
const { AssetsPage } = require("../pages/assets.page");

const ADVANCED_MODEL_INPUT_SCHEMA = {
  type: "object",
  properties: {
    text: {
      type: "string",
      description: "Input text to classify.",
    },
    language: {
      type: "string",
      description: "Optional ISO-639-1 language code.",
    },
  },
  required: ["text"],
  additionalProperties: false,
};
const ADVANCED_MODEL_INPUT_EXAMPLE = {
  text: "The validation framework can register advanced DAIMO metadata.",
  language: "en",
};

test("PT5-MH-02: provider can register a local model asset with valid metadata", async ({
  page,
  request,
  aiModelHubRuntime,
  captureStep,
  attachJson,
}) => {
  const assetsPage = new AssetsPage(page, aiModelHubRuntime);
  const suffix = `${Date.now()}`;
  const assetId = `pt5-mh-02-model-${suffix}`;
  const assetName = `PT5 MH 02 Model ${suffix}`;
  const baseUrl = `http://pt5-mh-02.local/assets/${assetId}`;
  const connectorAuthorization = await attachManagementAuthorizationRoutes(page, aiModelHubRuntime);

  await assetsPage.goto();
  await assetsPage.waitUntilReady();
  await assetsPage.switchToConnector(aiModelHubRuntime.providerConnectorName);

  const createDialog = await assetsPage.openCreateAssetDialog();
  await createDialog.fillCommonFields({
    id: assetId,
    name: assetName,
    contentType: aiModelHubRuntime.modelContentType,
  });
  await createDialog.selectFirstDataType();
  await createDialog.fillBaseUrl(baseUrl);
  await createDialog.enableMlMetadataHelper();
  await createDialog.fillMlMetadata({
    description: aiModelHubRuntime.modelDescription,
    version: aiModelHubRuntime.modelVersion,
    assetKind: "model",
    task: "text-classification",
  });
  await createDialog.fillAdvancedMlMetadata({
    modalities: ["text"],
    keywords: ["classification", "inference"],
    license: "Apache-2.0",
    maturity: "validated",
    runtimes: ["scikit-learn", "custom-python"],
    languages: ["en", "es"],
    architecture: "controlled-text-classifier",
    baseModel: "validation-baseline",
    parameterCount: "125M",
    artifactSize: "24",
    quantization: "none",
    performanceMetric: "accuracy",
    performanceDataset: "custom",
    performanceReport: `https://validation.local/reports/${assetId}`,
    format: "json",
    inferencePath: "/classify",
    inputSchemaDraft: "2020-12",
    inputSchema: ADVANCED_MODEL_INPUT_SCHEMA,
    inputExample: ADVANCED_MODEL_INPUT_EXAMPLE,
    intendedUse: "Controlled A5.2 validation of AI model publication metadata.",
    limitations: "Synthetic metadata for validation; not a production model card.",
    piiSafe: true,
    regulatedDomain: true,
    humanInLoop: true,
    latencyP95: "120",
    throughput: "45",
    rateLimits: "100 req/min",
    availabilityTier: "silver",
  });
  await createDialog.addProperty("version", aiModelHubRuntime.modelVersion);
  await createDialog.addProperty("shortDescription", aiModelHubRuntime.modelDescription);
  await createDialog.addProperty("assetType", "machineLearning");
  await createDialog.addProperty(
    "http://purl.org/dc/terms/description",
    aiModelHubRuntime.modelDescription,
  );
  await createDialog.addProperty(
    "http://www.w3.org/ns/dcat#keyword",
    JSON.stringify(["machine-learning", "pt5-mh-02", "playwright"]),
  );

  await expect(createDialog.createAssetButton).toBeEnabled();
  await expect(createDialog.errorLabel).toHaveCount(0);
  await captureStep(page, "pt5-mh-02-before-submit");

  await createDialog.submit();

  await expect(createDialog.root).toBeHidden({ timeout: 15000 });
  await expect(assetsPage.successAlert.filter({ hasText: /created successfully/i })).toBeVisible({
    timeout: 15000,
  });
  await expect(assetsPage.errorAlert).toHaveCount(0);
  const managementVisibility = await waitForLocalProviderAsset(request, aiModelHubRuntime, assetId, 20, 1000);
  const persistedAsset = managementVisibility.asset;

  await expect.soft(persistedAsset['@id'] || persistedAsset.id).toBe(assetId);
  await expect.soft(persistedAsset.properties.name).toBe(assetName);
  await expect.soft(persistedAsset.properties.version).toBe(aiModelHubRuntime.modelVersion);
  await expect.soft(persistedAsset.properties.shortDescription).toBe(aiModelHubRuntime.modelDescription);
  await expect.soft(persistedAsset.properties.assetType).toBe('machineLearning');
  await expect.soft(persistedAsset.properties.contenttype).toBe(aiModelHubRuntime.modelContentType);
  await expect.soft(persistedAsset.properties['daimo:short_description']).toBe(aiModelHubRuntime.modelDescription);
  await expect.soft(persistedAsset.properties['daimo:model_version']).toBe(aiModelHubRuntime.modelVersion);
  await expect.soft(persistedAsset.properties['daimo:asset_kind']).toBe('model');
  await expect.soft(persistedAsset.properties['daimo:pipeline_tag']).toBe('text-classification');
  await expect.soft(asArray(persistedAsset.properties['daimo:modality'])).toContain('text');
  await expect.soft(asArray(persistedAsset.properties['daimo:tags'])).toEqual(
    expect.arrayContaining(['classification', 'inference']),
  );
  await expect.soft(persistedAsset.properties['daimo:license']).toBe('Apache-2.0');
  await expect.soft(persistedAsset.properties['daimo:maturity_status']).toBe('validated');
  await expect.soft(asArray(persistedAsset.properties['daimo:library_name'])).toEqual(
    expect.arrayContaining(['scikit-learn', 'custom-python']),
  );
  await expect.soft(asArray(persistedAsset.properties['daimo:language'])).toEqual(
    expect.arrayContaining(['en', 'es']),
  );
  await expect.soft(persistedAsset.properties['daimo:architecture_family']).toBe('controlled-text-classifier');
  await expect.soft(persistedAsset.properties['daimo:base_model']).toBe('validation-baseline');
  await expect.soft(persistedAsset.properties['daimo:format']).toBe('json');
  await expect.soft(persistedAsset.properties['daimo:inference_path']).toBe('/classify');
  await expect.soft(persistedAsset.properties['daimo:input_schema_draft']).toBe('2020-12');
  await expect.soft(readJsonProperty(persistedAsset.properties['daimo:input_schema'])?.properties?.text?.type).toBe('string');
  await expect.soft(readJsonProperty(persistedAsset.properties['daimo:input_example'])?.language).toBe('en');
  await expect.soft(asArray(persistedAsset.properties['daimo:input_features']).some((field) => field.name === 'text')).toBe(true);
  await expect.soft(persistedAsset.properties['daimo:parameter_count']).toBe('125M');
  await expect.soft(persistedAsset.properties['daimo:artifact_size_mb']).toBe('24');
  await expect.soft(persistedAsset.properties['daimo:quantization']).toBe('none');
  await expect.soft(persistedAsset.properties['daimo:performance_metric']).toBe('accuracy');
  await expect.soft(persistedAsset.properties['daimo:performance_dataset']).toBe('custom');
  await expect.soft(persistedAsset.properties['daimo:intended_use']).toContain('A5.2 validation');
  await expect.soft(persistedAsset.properties['daimo:limitations']).toContain('Synthetic metadata');
  await expect.soft(persistedAsset.properties['daimo:pii_safe']).toBe(true);
  await expect.soft(persistedAsset.properties['daimo:regulated_domain']).toBe(true);
  await expect.soft(persistedAsset.properties['daimo:human_in_the_loop_required']).toBe(true);
  await expect.soft(persistedAsset.properties['daimo:latency_p95_ms']).toBe('120');
  await expect.soft(persistedAsset.properties['daimo:throughput_rps']).toBe('45');
  await expect.soft(persistedAsset.properties['daimo:rate_limits']).toBe('100 req/min');
  await expect.soft(persistedAsset.properties['daimo:availability_tier']).toBe('silver');
  await expect
    .soft(persistedAsset.properties['http://www.w3.org/ns/dcat#keyword'] || [])
    .toContain('pt5-mh-02');
  await expect.soft(persistedAsset.dataAddress.type).toBe('HttpData');
  await expect.soft(persistedAsset.dataAddress.baseUrl).toBe(baseUrl);

  await captureStep(page, "pt5-mh-02-created-model");
  await attachJson("pt5-mh-02-state", {
    route: aiModelHubRuntime.assetsPath,
    connector: aiModelHubRuntime.providerConnectorName,
    assetId,
    assetName,
    baseUrl,
    contentType: aiModelHubRuntime.modelContentType,
    mlMetadataEnabled: true,
    advancedMlMetadata: {
      modalities: persistedAsset.properties['daimo:modality'],
      runtimes: persistedAsset.properties['daimo:library_name'],
      inputSchemaDraft: persistedAsset.properties['daimo:input_schema_draft'],
      inferencePath: persistedAsset.properties['daimo:inference_path'],
      safety: {
        piiSafe: persistedAsset.properties['daimo:pii_safe'],
        regulatedDomain: persistedAsset.properties['daimo:regulated_domain'],
        humanInLoop: persistedAsset.properties['daimo:human_in_the_loop_required'],
      },
    },
    managementVisibility,
    authorizedConnectors: Object.keys(connectorAuthorization),
  });
});

function asArray(value) {
  if (Array.isArray(value)) {
    return value;
  }
  if (value === undefined || value === null || value === "") {
    return [];
  }
  return [value];
}

function readJsonProperty(value) {
  if (typeof value !== "string") {
    return value;
  }
  try {
    return JSON.parse(value);
  } catch {
    return undefined;
  }
}
