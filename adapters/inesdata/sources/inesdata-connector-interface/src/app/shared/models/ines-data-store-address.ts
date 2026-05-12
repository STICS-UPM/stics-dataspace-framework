import { BaseDataAddress } from "@think-it-labs/edc-connector-client";

export interface InesDataStoreAddress extends BaseDataAddress{
  type: 'InesDataStore';
  folder?: string;
  file?: any;
}
