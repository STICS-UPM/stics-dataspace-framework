import { UiPolicy } from "./policy/ui-policy";

/**
 * Catalog Data Offer's Contract Offer as required by the UI
 * @export
 * @interface ContractOffer
 */
 export declare interface ContractOffer {
  /**
   * Contract Offer ID
   * @type {string}
   * @memberof UiContractOffer
   */
  contractOfferId: string;
  /**
   *
   * @type {UiPolicy}
   * @memberof UiContractOffer
   */
  policy: UiPolicy;
}
