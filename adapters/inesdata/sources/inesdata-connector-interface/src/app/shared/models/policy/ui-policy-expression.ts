import { UiPolicyConstraint } from "./ui-policy-constraint";
import { UiPolicyExpressionType } from "./ui-policy-expression-type";

/**
 * ODRL constraint as supported by the sovity product landscape
 * @export
 * @interface UiPolicyExpression
 */
export declare interface UiPolicyExpression {
  /**
   *
   * @type {UiPolicyExpressionType}
   * @memberof UiPolicyExpression
   */
  type: UiPolicyExpressionType;
  /**
   * Only for types AND, OR. List of sub-expressions to be evaluated according to the expressionType.
   * @type {Array<UiPolicyExpression>}
   * @memberof UiPolicyExpression
   */
  expressions?: Array<UiPolicyExpression>;
  /**
   *
   * @type {UiPolicyConstraint}
   * @memberof UiPolicyExpression
   */
  constraint?: UiPolicyConstraint;
}
