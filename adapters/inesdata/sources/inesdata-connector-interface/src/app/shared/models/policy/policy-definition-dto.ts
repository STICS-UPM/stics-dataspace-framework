import { UiPolicy } from "./ui-policy";

/**
 * Policy Definition as required for the Policy Definition Page
 * @export
 * @interface PolicyDefinitionDto
 */
 export declare interface PolicyDefinitionDto {
  /**
   * Policy Definition ID
   * @type {string}
   * @memberof PolicyDefinitionDto
   */
  policyDefinitionId: string;
  /**
   *
   * @type {UiPolicy}
   * @memberof PolicyDefinitionDto
   */
  policy: UiPolicy;
}
