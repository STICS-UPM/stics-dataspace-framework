import { DataOffer } from './data-offer';
import { Asset } from './edc-connector-entities';

export type AiModelExecutionSource = 'own' | 'federated';
export type AiModelRequestShape = 'single' | 'batch';
export type AiModelBenchmarkModelType = 'output' | 'metric';
export type AiModelMetricDirection = 'higher' | 'lower';

export interface AiModelExecutionInputFeature {
  name: string;
  type: string;
  required: boolean;
  description?: string;
  minValue?: number;
  maxValue?: number;
}

export interface AiModelExecutionItem {
  id: string;
  name: string;
  provider: string;
  source: AiModelExecutionSource;
  isLocal: boolean;
  hasAgreement: boolean;
  contentType: string;
  description: string;
  executionPath: string;
  httpMethodDefault: string;
  tasks: string[];
  subtasks?: string[];
  algorithms: string[];
  frameworks: string[];
  inputFeatures: AiModelExecutionInputFeature[];
  inputColumns?: string[];
  inputSchema?: unknown;
  inputExample?: unknown;
  requestShape?: AiModelRequestShape;
  benchmarkModelType?: AiModelBenchmarkModelType;
  targetFields?: string[];
  predictionFields?: string[];
  supportedMetrics?: string[];
  metricDirections?: Record<string, AiModelMetricDirection>;
  positiveLabel?: string;
  scoreField?: string;
  rawAsset?: Asset;
  rawOffer?: DataOffer;
}

export interface ModelExecutionRequestPayload {
  assetId: string;
  payload: unknown;
  correlationId?: string;
  benchmarkRunId?: string;
  modelName?: string;
  method?: string;
  path?: string;
  headers?: Record<string, string>;
}

export interface ModelExecutionResponsePayload {
  statusCode: number;
  contentType: string;
  body: string;
  parsedBody?: unknown;
}
