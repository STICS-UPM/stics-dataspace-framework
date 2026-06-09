import { DataOffer } from './data-offer';
import { Asset } from './edc-connector-entities';

export type BenchmarkDatasetSource = 'own' | 'federated';

export interface BenchmarkDatasetMapping {
  input: string[];
  label: string;
}

export interface BenchmarkDatasetAsset {
  id: string;
  name: string;
  description: string;
  provider: string;
  source: BenchmarkDatasetSource;
  isLocal: boolean;
  hasAgreement: boolean;
  assetType: string;
  contentType: string;
  format: string;
  storageType: string;
  fileName: string;
  tags: string[];
  rawProperties: Record<string, unknown>;
  rawAsset?: Asset;
  rawOffer?: DataOffer;
}
