import { modelServerBaseUrlFromUrl, modelServerUrlForPath } from "../../../shared/utils/model-server-url";

export const DEFAULT_AI_MODEL_PATH = "/api/v1/nlp/ecommerce-sentiment";
export const DEFAULT_AI_MODEL_PAYLOAD = {
  text: "This product is excellent and very useful",
};

export const TEXT_MODEL_INPUT_FEATURES = [
  {
    name: "text",
    type: "string",
    required: true,
    description: "Text to analyze",
  },
];

export const TEXT_MODEL_INPUT_SCHEMA = {
  type: "object",
  required: ["text"],
  properties: {
    text: {
      type: "string",
      description: "Text to analyze",
    },
  },
};

export const TEXT_MODEL_BENCHMARK_ROWS = [
  {
    input: {
      text: "This product is excellent and very useful",
    },
    expected_label: "positive",
  },
  {
    input: {
      text: "The delivery was late and the product was broken",
    },
    expected_label: "negative",
  },
];

const DEFAULT_SEMANTIC_QUERY_PATH =
  "/?query=SELECT%20*%20WHERE%20%7B%20%3Fs%20%3Fp%20%3Fo%20.%20%7D%20LIMIT%201";

type ModelMetadataArgs = {
  task: string;
  subtask: string;
  algorithm: string;
  library: string;
  framework: string;
  software: string;
  inferencePath: string;
};

type AiModelAssetArgs = {
  suffix: string;
  modelUrl: string;
  modelPath: string;
  modelName?: string;
  task?: string;
  subtask?: string;
  algorithm?: string;
  library?: string;
  framework?: string;
  software?: string;
};

export function normalizePath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "/";
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

export function aiModelHubModelPath(): string {
  return normalizePath(process.env.UI_AI_MODEL_HUB_MODEL_PATH || DEFAULT_AI_MODEL_PATH);
}

export function aiModelHubModelUrl(componentsNamespace: string): string {
  return modelServerUrlForPath(aiModelHubModelPath(), componentsNamespace);
}

export function semanticVirtualizationDataUrl(dataspace: string): string {
  const explicit = (process.env.UI_SEMANTIC_VIRTUALIZATION_DATA_URL || "").trim();
  if (explicit) {
    return explicit;
  }

  const namespace = (process.env.UI_COMPONENTS_NAMESPACE || process.env.COMPONENTS_NAMESPACE || "components").trim();
  const queryPath = normalizePath(
    process.env.UI_SEMANTIC_VIRTUALIZATION_QUERY_PATH ||
      process.env.SEMANTIC_VIRTUALIZATION_QUERY_PATH ||
      DEFAULT_SEMANTIC_QUERY_PATH,
  );
  return `http://${dataspace}-semantic-virtualization.${namespace}.svc.cluster.local:8000${queryPath}`;
}

export function aiModelMetadataAliases({
  task,
  subtask,
  algorithm,
  library,
  framework,
  software,
  inferencePath,
}: ModelMetadataArgs): Record<string, unknown> {
  const inputFeatures = JSON.stringify(TEXT_MODEL_INPUT_FEATURES);
  const inputSchema = JSON.stringify(TEXT_MODEL_INPUT_SCHEMA);
  const inputExample = JSON.stringify(DEFAULT_AI_MODEL_PAYLOAD);

  return {
    "daimo:asset_kind": "model",
    "https://w3id.org/daimo/ns#asset_kind": "model",
    "https://pionera.ai/edc/daimo#asset_kind": "model",
    "daimo:task": task,
    "https://w3id.org/daimo/ns#task": task,
    "https://pionera.ai/edc/daimo#task": task,
    "daimo:pipeline_tag": task,
    "https://pionera.ai/edc/daimo#pipeline_tag": task,
    "daimo:subtask": subtask,
    "https://w3id.org/daimo/ns#subtask": subtask,
    "https://pionera.ai/edc/daimo#subtask": subtask,
    "daimo:algorithm": algorithm,
    "https://w3id.org/daimo/ns#algorithm": algorithm,
    "https://pionera.ai/edc/daimo#algorithm": algorithm,
    "daimo:library": library,
    "daimo:library_name": library,
    "https://w3id.org/daimo/ns#library": library,
    "https://pionera.ai/edc/daimo#library": library,
    "https://pionera.ai/edc/daimo#library_name": library,
    "daimo:license": "Apache-2.0",
    "https://pionera.ai/edc/daimo#license": "Apache-2.0",
    "daimo:datasets": ["validation-controlled"],
    "https://pionera.ai/edc/daimo#datasets": ["validation-controlled"],
    "daimo:language": ["en"],
    "https://pionera.ai/edc/daimo#language": ["en"],
    "daimo:base_model": "controlled-httpdata",
    "https://pionera.ai/edc/daimo#base_model": "controlled-httpdata",
    "daimo:model_version": "1.0.0",
    "https://pionera.ai/edc/daimo#model_version": "1.0.0",
    "daimo:input_schema_draft": "https://json-schema.org/draft/2020-12/schema",
    "https://pionera.ai/edc/daimo#input_schema_draft": "https://json-schema.org/draft/2020-12/schema",
    "daimo:framework": framework,
    "https://w3id.org/daimo/ns#framework": framework,
    "https://pionera.ai/edc/daimo#framework": framework,
    "daimo:software": software,
    "https://w3id.org/daimo/ns#software": software,
    "https://pionera.ai/edc/daimo#software": software,
    "daimo:inference_path": inferencePath,
    "https://w3id.org/daimo/ns#inference_path": inferencePath,
    "https://pionera.ai/edc/daimo#inference_path": inferencePath,
    "daimo:input_features": inputFeatures,
    "https://w3id.org/daimo/ns#input_features": inputFeatures,
    "https://pionera.ai/edc/daimo#input_features": inputFeatures,
    "daimo:input_schema": inputSchema,
    "https://w3id.org/daimo/ns#input_schema": inputSchema,
    "https://pionera.ai/edc/daimo#input_schema": inputSchema,
    "daimo:input_example": inputExample,
    "https://w3id.org/daimo/ns#input_example": inputExample,
    "https://pionera.ai/edc/daimo#input_example": inputExample,
    "daimo:format": "json",
    "daimo:contenttype": "application/json",
    task,
    subtask,
    algorithm,
    library,
    framework,
    software,
    inference_path: inferencePath,
    inferencePath,
    input_features: inputFeatures,
    inputFeatures: TEXT_MODEL_INPUT_FEATURES,
    input_schema: inputSchema,
    inputSchema: TEXT_MODEL_INPUT_SCHEMA,
    input_example: inputExample,
    inputExample: DEFAULT_AI_MODEL_PAYLOAD,
  };
}

export function aiModelAssetOptions({
  suffix,
  modelUrl,
  modelPath,
  modelName,
  task = "text-classification",
  subtask = "sentiment-analysis",
  algorithm = "controlled-httpdata",
  library = "controlled-httpdata",
  framework = "controlled-httpdata",
  software = "controlled-httpdata",
}: AiModelAssetArgs): Record<string, unknown> {
  const name = modelName || `EDC AI Model Hub model ${suffix}`;
  const tags = ["validation", "ai-model-hub", "inference", "endpoint", "model-serving", "A5.2"];

  return {
    sourceObjectName: `edc-ai-model-${suffix}.json`,
    name,
    version: "1.0.0",
    shortDescription: "AI Model Hub endpoint exposed as an EDC HttpData asset",
    description: "Machine-learning model endpoint governed through EDC as a contractual HttpData asset.",
    assetType: "machineLearning",
    keywords: tags,
    properties: {
      "asset:prop:type": "machineLearning",
      contenttype: "application/json",
      "dcat:keyword": tags,
      "daimo:tags": tags,
      "https://pionera.ai/edc/daimo#tags": tags,
      ...aiModelMetadataAliases({
        task,
        subtask,
        algorithm,
        library,
        framework,
        software,
        inferencePath: modelPath,
      }),
    },
    dataAddress: {
      type: "HttpData",
      baseUrl: modelServerBaseUrlFromUrl(modelUrl, modelPath),
      method: "POST",
      name: `edc-ai-model-${suffix}.json`,
      proxyPath: "true",
    },
  };
}

export function benchmarkDatasetAssetOptions(suffix: string): Record<string, unknown> {
  const rows = JSON.stringify(TEXT_MODEL_BENCHMARK_ROWS);
  const tags = ["validation", "ai-model-hub", "dataset", "benchmark", "ground-truth", "A5.2"];

  return {
    sourceObjectName: `edc-ai-model-benchmark-dataset-${suffix}.json`,
    name: `EDC AI Model Hub benchmark dataset ${suffix}`,
    version: "1.0.0",
    shortDescription: "Inline benchmark dataset used by the EDC AI Model Hub validation flow",
    description: "Small controlled dataset used to validate model comparison screens from the EDC dashboard.",
    assetType: "dataset",
    keywords: tags,
    properties: {
      "asset:prop:type": "dataset",
      contenttype: "application/json",
      "dcat:keyword": tags,
      "daimo:asset_kind": "dataset",
      "daimo:task": "text-classification",
      "daimo:tags": tags,
      "daimo:benchmark_dataset": rows,
      "daimo:benchmark_dataset_mapping": JSON.stringify({
        inputPath: "input",
        expectedPath: "expected_label",
        predictionPath: "result.label",
      }),
      "https://pionera.ai/edc/daimo#benchmark_dataset": rows,
      benchmark_dataset: rows,
      benchmarkDataset: TEXT_MODEL_BENCHMARK_ROWS,
    },
    dataAddress: {
      type: "HttpData",
      baseUrl: "https://jsonplaceholder.typicode.com/todos/1",
      method: "GET",
      name: `edc-ai-model-benchmark-dataset-${suffix}.json`,
    },
  };
}

export function semanticVirtualizationAssetOptions(args: {
  suffix: string;
  semanticDataUrl: string;
  sourceObjectName?: string;
}): Record<string, unknown> {
  const sourceObjectName = args.sourceObjectName || "gtfs_bench_official_materialized.ttl";
  return {
    sourceObjectName,
    name: `GTFS-Bench RDF via Semantic Virtualization ${args.suffix}`,
    version: "official-mini-v1",
    shortDescription: "Official-derived GTFS-Bench RDF output exposed as HttpData for EDC UI validation",
    description:
      "Semantic Virtualization RDF/Turtle output derived from the official GTFS-Bench fixture and exposed through EDC as a contractual HttpData asset.",
    assetType: "semantic-virtualization-gtfs-bench-rdf-output",
    keywords: [
      "validation",
      "semantic-virtualization",
      "HttpData",
      "GTFS-Madrid-Bench",
      "gtfs-bench",
      "mobility",
      "rdf",
      "A5.2",
    ],
    properties: {
      "daimo:asset_kind": "dataset",
      "daimo:sourceDataset": "GTFS-Madrid-Bench",
      "daimo:domain": "mobility",
      "daimo:task": "semantic-virtualization-gtfs-bench-official-materialization",
    },
    dataAddress: {
      type: "HttpData",
      baseUrl: args.semanticDataUrl,
      name: sourceObjectName,
    },
  };
}
