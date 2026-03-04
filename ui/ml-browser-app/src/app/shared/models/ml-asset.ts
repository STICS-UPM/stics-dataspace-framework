export interface MLAsset {
  id: string;
  name: string;
  version: string;
  description: string;
  shortDescription: string;
  assetType: string;
  contentType: string;
  byteSize: string;
  format: string;
  keywords: string[];
  
  // ML-specific fields (from assetData)
  tasks: string[];
  subtasks: string[];
  algorithms: string[];
  libraries: string[];
  frameworks: string[];
  modelType: string;

  // Storage information (from dataAddress)
  storageType?: string;
  fileName?: string;
  
  // Multi-tenancy: owner and local/external indicator
  owner?: string; // Connector ID of the owner (e.g., 'conn-oeg-demo')
  isLocal?: boolean; // true if the asset belongs to the authenticated user
  
  // Contract information
  hasContractOffers?: boolean;
  contractOffers?: unknown[];
  hasAgreement?: boolean;
  negotiationInProgress?: boolean;
  endpointUrl?: string;
  participantId?: string;
  
  // Full data
  assetData: Record<string, unknown>;
  rawProperties: Record<string, unknown>;
  originator: string; // 'Local Connector' or 'Federated Catalog'
}
