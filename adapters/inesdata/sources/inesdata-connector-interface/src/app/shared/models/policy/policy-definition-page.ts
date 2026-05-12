import { PolicyDefinitionDto } from "./policy-definition-dto";

/**
 * All data for the policy definition page as required by the UI
 * @export
 * @interface PolicyDefinitionPage
 */
 export declare interface PolicyDefinitionPage {
  /**
   * Policy Definition Entries
   * @type {Array<PolicyDefinitionDto>}
   * @memberof PolicyDefinitionPage
   */
  policies: Array<PolicyDefinitionDto>;
}
