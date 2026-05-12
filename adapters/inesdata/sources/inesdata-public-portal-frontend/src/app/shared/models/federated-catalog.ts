import { DataOffer } from './data-offer';

export interface FederatedCatalog {
  datasets: DataOffer[];
  totalElements: number;
}
