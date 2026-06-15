export const AI_MODEL_HUB_MODEL_VOCABULARY_ID = "JS_DAIMO_Model";
export const AI_MODEL_HUB_DATASET_VOCABULARY_ID = "JS_DAIMO_Dataset";

type InputFeature = {
  name?: unknown;
  type?: unknown;
  description?: unknown;
  nullable?: unknown;
};

type ModelDaimoMetadataArgs = {
  task?: string;
  taskType?: string;
  taskCategory?: string;
  subtask?: string;
  subtaskDescription?: string;
  modality?: string[];
  endpointBehavior?: "prediction" | "metric" | "embedding" | "ranking" | "explanation" | "artifact" | "other";
  requestShape?: "single" | "batch";
  description?: string;
  libraryName?: string;
  language?: string[];
  license?: string;
  inputFeatures?: unknown[];
  inputSchema?: unknown;
  inputExample?: unknown;
  metrics?: string[];
};

type DatasetDaimoMetadataArgs = {
  task?: string;
  taskType?: string;
  taskCategory?: string;
  subtask?: string;
  subtaskDescription?: string;
  modality?: string[];
  input: string[];
  label: string;
  labelType?: "continuous" | "binary" | "categorical" | "span" | "sequence" | "other";
  language?: string[];
  license?: string;
  format?: "csv" | "json" | "jsonl" | "parquet" | "images" | "other";
  keywords?: string[];
  datasetVersion?: string;
  datasetRole?: "training" | "validation" | "test" | "benchmark" | "external-validation";
  protocol?: "holdout-test-set" | "cross-validation" | "external-validation" | "online-evaluation" | "custom";
};

const MODEL_SUBTASKS = new Set([
  "text-classification",
  "token-classification",
  "question-answering",
  "text-generation",
  "summarization",
  "translation",
  "image-classification",
  "object-detection",
  "image-segmentation",
  "tabular-classification",
  "tabular-regression",
  "time-series-forecasting",
  "speech-recognition",
  "text-to-image",
  "embedding",
  "reranking",
  "other",
]);

function normalizeTaskType(value?: string): string {
  const normalized = (value || "").toLowerCase();
  if (normalized.includes("regression")) return "regression";
  if (normalized.includes("generation")) return "generation";
  if (normalized.includes("ranking")) return "ranking";
  if (normalized.includes("retrieval")) return "retrieval";
  if (normalized.includes("forecast")) return "forecasting";
  if (normalized.includes("segmentation")) return "segmentation";
  if (normalized.includes("detection")) return "detection";
  if (normalized.includes("embedding")) return "embedding";
  if (normalized.includes("anomaly")) return "anomaly_detection";
  return "classification";
}

function normalizeTaskCategory(value?: string): string {
  const normalized = (value || "").toLowerCase();
  if (normalized.includes("image") || normalized.includes("vision")) return "Computer vision";
  if (normalized.includes("tabular") || normalized.includes("regression")) return "Tabular";
  if (normalized.includes("time") || normalized.includes("forecast")) return "Time series";
  if (normalized.includes("audio") || normalized.includes("speech")) return "Audio";
  if (normalized.includes("multimodal")) return "Multimodal";
  if (normalized.includes("event")) return "Predictive event";
  return "Natural Language Processing";
}

function normalizeModelSubtask(value?: string): string {
  const normalized = (value || "").toLowerCase();
  if (MODEL_SUBTASKS.has(normalized)) return normalized;
  if (normalized.includes("token") || normalized.includes("span") || normalized.includes("5w1h")) {
    return "token-classification";
  }
  if (normalized.includes("regression")) return "tabular-regression";
  if (normalized.includes("forecast")) return "time-series-forecasting";
  if (normalized.includes("embedding")) return "embedding";
  if (normalized.includes("ranking") || normalized.includes("rerank")) return "reranking";
  return "text-classification";
}

function normalizeInputType(value: unknown): string {
  const normalized = String(value || "string").toLowerCase();
  if (["string", "integer", "number", "boolean", "array", "object"].includes(normalized)) {
    return normalized;
  }
  return "string";
}

function inputDefinition(inputFeatures: unknown[] = [], inputSchema?: unknown): Record<string, unknown> {
  const fields = inputFeatures
    .filter((field): field is InputFeature => field !== null && typeof field === "object" && "name" in field)
    .map((field) => ({
      name: String(field.name),
      type: normalizeInputType(field.type),
      ...(field.description !== undefined ? { description: String(field.description) } : {}),
      ...(field.nullable !== undefined ? { nullable: Boolean(field.nullable) } : {}),
    }));

  return {
    ...(fields.length > 0 ? { fields } : {}),
    ...(inputSchema !== undefined ? { jsonSchema: JSON.stringify(inputSchema) } : {}),
  };
}

export function aiModelHubDaimoModelAssetData(args: ModelDaimoMetadataArgs): Record<string, unknown> {
  const taskSeed = args.task || args.taskType || args.subtask;
  const inputSchema = inputDefinition(args.inputFeatures, args.inputSchema);
  const metadata: Record<string, unknown> = {
    "daimo:modality": args.modality || ["text"],
    "daimo:taskType": args.taskType || normalizeTaskType(taskSeed),
    "daimo:taskCategory": args.taskCategory || normalizeTaskCategory(taskSeed),
    "daimo:subtask": normalizeModelSubtask(args.subtask || args.task),
    "daimo:subtaskDescription": args.subtaskDescription || args.subtask || args.task || "AI Model Hub validation model",
    "daimo:endpointBehavior": args.endpointBehavior || "prediction",
    "daimo:requestShape": args.requestShape || "single",
    "dct:description": args.description || "AI Model Hub model endpoint exposed as HttpData.",
    "daimo:libraryName": args.libraryName || "Custom",
    "dct:language": args.language || ["Spanish"],
    "dct:license": args.license || "apache-2.0",
    "daimo:inputSchema": inputSchema,
    "daimo:inputExample": JSON.stringify(args.inputExample || {}),
    "daimo:metrics": args.metrics || ["Accuracy", "Precision", "Recall", "F1"],
  };
  return { [AI_MODEL_HUB_MODEL_VOCABULARY_ID]: metadata };
}

export function aiModelHubDaimoDatasetAssetData(args: DatasetDaimoMetadataArgs): Record<string, unknown> {
  const taskSeed = args.task || args.taskType || args.subtask;
  const metadata: Record<string, unknown> = {
    "daimo:modality": args.modality || ["text"],
    "daimo:taskType": args.taskType || normalizeTaskType(taskSeed),
    "daimo:taskCategory": args.taskCategory || normalizeTaskCategory(taskSeed),
    "daimo:subtask": normalizeModelSubtask(args.subtask || args.task),
    "daimo:subtaskDescription": args.subtaskDescription || args.subtask || args.task || "AI Model Hub benchmark dataset",
    "daimo:input": args.input,
    "daimo:label": args.label,
    "daimo:labelType": args.labelType || "categorical",
    "dct:language": args.language || ["Spanish"],
    "dct:license": args.license || "apache-2.0",
    "dct:format": args.format || "json",
    "dcat:keyword": args.keywords || ["benchmark", "validation"],
    "daimo:datasetVersion": args.datasetVersion || "1.0.0",
    "daimo:datasetRole": args.datasetRole || "test",
    "daimo:protocol": args.protocol || "holdout-test-set",
  };
  return { [AI_MODEL_HUB_DATASET_VOCABULARY_ID]: metadata };
}
