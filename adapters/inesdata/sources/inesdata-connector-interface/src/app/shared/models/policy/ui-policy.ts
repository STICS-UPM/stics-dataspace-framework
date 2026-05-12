import { UiPolicyExpression } from "./ui-policy-expression";

/**
 * Type-Safe OpenAPI generator friendly ODLR policy subset as endorsed by sovity.
 * @export
 * @interface UiPolicy
 */
 export declare interface UiPolicy {
  /**
   * EDC Policy JSON-LD. This is required because the EDC requires the full policy when initiating contract negotiations.
   * @type {string}
   * @memberof UiPolicy
   */
  policyJsonLd: string;
  /**
   *
   * @type {UiPolicyExpression}
   * @memberof UiPolicy
   */
  expression?: UiPolicyExpression;
  /**
   * When trying to reduce the policy JSON-LD to our opinionated subset of functionalities, many fields and functionalities are unsupported. Should any discrepancies occur during the mapping process, we'll collect them here.
   * @type {Array<string>}
   * @memberof UiPolicy
   */
  errors: Array<string>;
}
