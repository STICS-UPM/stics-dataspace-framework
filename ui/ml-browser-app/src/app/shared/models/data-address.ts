/**
 * Data Address Models for EDC Asset Creation
 * Supports HTTP, Amazon S3, and DataSpacePrototypeStore storage types
 */

/**
 * Base interface for all data addresses
 */
export interface DataAddress {
  '@type': string;
  type?: string;  // EDC compatibility
}

/**
 * HTTP Data Address configuration
 * Used for assets accessible via HTTP/HTTPS
 */
export interface HttpDataAddress extends DataAddress {
  '@type': 'HttpData';
  type: 'HttpData';  // EDC compatibility
  name: string;
  baseUrl: string;
  path?: string;
  authKey?: string;
  authCode?: string;
  secretName?: string;
  contentType?: string;
  proxyBody?: string;
  proxyPath?: string;
  proxyQueryParams?: string;
  proxyMethod?: string;
}

/**
 * Amazon S3 Data Address configuration
 * Used for assets stored in S3-compatible storage
 */
export interface AmazonS3DataAddress extends DataAddress {
  '@type': 'AmazonS3';
  type: 'AmazonS3';  // EDC compatibility
  region: string;
  bucketName: string;
  accessKeyId: string;
  secretAccessKey: string;
  endpointOverride: string;
  keyPrefix?: string;
  folderName?: string;
}

/**
 * DataSpacePrototypeStore Data Address configuration
 * Used for assets stored in connector's internal storage
 */
export interface DataSpacePrototypeStoreAddress extends DataAddress {
  '@type': 'DataSpacePrototypeStore';
  type: 'DataSpacePrototypeStore';  // EDC compatibility
  folder?: string;
  file?: File;
}

/**
 * Storage type identifiers
 */
export const DATA_ADDRESS_TYPES = {
  httpData: 'HttpData',
  amazonS3: 'AmazonS3',
  dataSpacePrototypeStore: 'DataSpacePrototypeStore'
} as const;

/**
 * Storage type configuration for UI
 */
export interface StorageType {
  id: string;
  name: string;
}

/**
 * Available storage types
 */
export const STORAGE_TYPES: StorageType[] = [
  { id: DATA_ADDRESS_TYPES.httpData, name: 'HTTP Data' },
  { id: DATA_ADDRESS_TYPES.amazonS3, name: 'Amazon S3' },
  { id: DATA_ADDRESS_TYPES.dataSpacePrototypeStore, name: 'DataSpacePrototype Store' }
];
