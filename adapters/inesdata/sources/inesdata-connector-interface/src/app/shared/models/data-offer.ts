import { ContractOffer } from './contract-offer';

export interface DataOffer {
  assetId: string;
  properties: any;
  endpointUrl: string;
  contractOffers: ContractOffer[];
  originator: string;
}
