import { DataOffer } from './data-offer';
import { Asset } from './edc-connector-entities';

export type AiModelExecutionSource = 'own' | 'federated';

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
  algorithms: string[];
  frameworks: string[];
  inputFeatures: AiModelExecutionInputFeature[];
  inputSchema?: unknown;
  inputExample?: unknown;
  rawAsset?: Asset;
  rawOffer?: DataOffer;
}

export interface ModelExecutionRequestPayload {
  assetId: string;
  payload: unknown;
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
