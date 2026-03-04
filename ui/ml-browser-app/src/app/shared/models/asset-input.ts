import { DataAddress } from './data-address';
import { MLMetadata } from './ml-metadata';

/**
 * Asset Input for creating EDC assets
 * This structure matches the expected format for the EDC Management API
 */
export interface AssetInput {
  '@id': string;
  properties: AssetProperties;
  dataAddress: DataAddress;
  blob?: Blob; // For DataSpacePrototypeStore file uploads
}

/**
 * Asset properties structure
 * Combines general asset information with ML-specific metadata
 */
export interface AssetProperties {
  // General Information (required)
  name: string;
  version: string;
  contenttype?: string;
  assetType: string;
  shortDescription: string;
  'dcterms:description': string;  // Full description (rich text)
  'dcat:keyword': string[];       // Array of keywords
  
  // Optional general properties
  'dcat:byteSize'?: string;
  'dcterms:format'?: string;
  
  // ML-specific metadata
  assetData?: {
    [key: string]: MLMetadata | unknown;
  };
  
  // Additional custom properties
  [key: string]: unknown;
}

/**
 * Form data structure for asset creation
 * Used internally in the form component
 */
export interface AssetFormData {
  // Basic Information
  id: string;
  name: string;
  version: string;
  contenttype: string;
  assetType: string;
  shortDescription: string;
  description: string;
  keywords: string;  // Comma-separated string, converted to array
  byteSize?: string;
  format?: string;
  
  // ML Metadata
  mlMetadata: MLMetadata;
  
  // Storage Configuration
  storageTypeId: string;
  dataAddress: DataAddress;
}

/**
 * Validation result for asset form
 */
export interface AssetValidationResult {
  valid: boolean;
  errors: string[];
}

/**
 * Helper function to convert form data to asset input
 */
export function convertFormDataToAssetInput(formData: AssetFormData): AssetInput {
  const properties: AssetProperties = {
    name: formData.name,
    version: formData.version,
    contenttype: formData.contenttype || 'application/octet-stream',
    assetType: formData.assetType,
    shortDescription: formData.shortDescription,
    'dcterms:description': formData.description,
    'dcat:keyword': formData.keywords.split(',').map(k => k.trim()).filter(k => k.length > 0)
  };
  
  if (formData.byteSize) {
    properties['dcat:byteSize'] = formData.byteSize;
  }
  
  if (formData.format) {
    properties['dcterms:format'] = formData.format;
  }
  
  // Add ML metadata if present
  if (formData.mlMetadata && Object.keys(formData.mlMetadata).length > 0) {
    properties.assetData = {
      mlMetadata: formData.mlMetadata
    };
  }
  
  return {
    '@id': formData.id,
    properties,
    dataAddress: formData.dataAddress
  };
}

/**
 * Helper function to parse keywords string to array
 */
export function parseKeywords(keywords: string): string[] {
  return keywords.split(',').map(k => k.trim()).filter(k => k.length > 0);
}

/**
 * Helper function to validate required fields
 */
export function validateAssetFormData(formData: Partial<AssetFormData>): AssetValidationResult {
  const errors: string[] = [];
  
  if (!formData.id || formData.id.trim() === '') {
    errors.push('ID is required');
  }
  
  if (!formData.name || formData.name.trim() === '') {
    errors.push('Name is required');
  }
  
  if (!formData.version || formData.version.trim() === '') {
    errors.push('Version is required');
  }
  
  if (!formData.assetType || formData.assetType.trim() === '') {
    errors.push('Asset type is required');
  }
  
  if (!formData.shortDescription || formData.shortDescription.trim() === '') {
    errors.push('Short description is required');
  }
  
  if (!formData.description || formData.description.trim() === '') {
    errors.push('Description is required');
  }
  
  if (!formData.keywords || formData.keywords.trim() === '') {
    errors.push('Keywords are required');
  }
  
  if (!formData.storageTypeId || formData.storageTypeId.trim() === '') {
    errors.push('Storage type is required');
  }
  
  return {
    valid: errors.length === 0,
    errors
  };
}
