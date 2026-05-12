import { BaseDataAddress } from "@think-it-labs/edc-connector-client";

export interface AmazonS3DataAddress extends BaseDataAddress {
  type: 'AmazonS3';
  region: string;
  bucketName?: string;
  keyPrefix?: string;
  folderName?: string;
  accessKeyId?: string;
  secretAccessKey?: string;
  endpointOverride?: string;
}
