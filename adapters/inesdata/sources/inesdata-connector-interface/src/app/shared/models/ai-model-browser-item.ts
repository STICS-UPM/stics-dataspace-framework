import { DataOffer } from './data-offer';
import { Asset } from './edc-connector-entities';

export type AiModelBrowserSource = 'own' | 'federated';

export interface AiModelBrowserItem {
  id: string;
  name: string;
  version: string;
  description: string;
  shortDescription: string;
  keywords: string[];
  assetType: string;
  contentType: string;
  format: string;
  storageType: string;
  fileName: string;
  tasks: string[];
  subtasks: string[];
  algorithms: string[];
  libraries: string[];
  frameworks: string[];
  software: string[];
  provider: string;
  source: AiModelBrowserSource;
  hasContract: boolean;
  rawAsset?: Asset;
  rawOffer?: DataOffer;
}
