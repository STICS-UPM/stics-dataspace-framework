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
  taskTypes: string[];
  modalities: string[];
  subtasks: string[];
  endpointBehaviors: string[];
  libraries: string[];
  languages: string[];
  licenses: string[];
  provider: string;
  source: AiModelBrowserSource;
  hasContract: boolean;
  rawAsset?: Asset;
  rawOffer?: DataOffer;
}
