import { UiPolicyExpression } from "./ui-policy-expression";

/**
 * Create a Policy Definition
 * @export
 * @interface PolicyDefinitionCreateDto
 */
export declare interface PolicyDefinitionCreateDto {
  /**
   * Policy Definition ID
   * @type {string}
   * @memberof PolicyDefinitionCreateDto
   */
  policyDefinitionId: string;
  /**
   *
   * @type {UiPolicyExpression}
   * @memberof PolicyDefinitionCreateDto
   */
  expression: UiPolicyExpression;
}
