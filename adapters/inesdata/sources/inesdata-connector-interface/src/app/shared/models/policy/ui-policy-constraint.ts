
/**
 * Type-Safe ODRL Policy Operator as supported by the sovity product landscape
 * @export
 */
export declare const OperatorDto: {
  readonly Eq: "EQ";
  readonly Neq: "NEQ";
  readonly Gt: "GT";
  readonly Geq: "GEQ";
  readonly Lt: "LT";
  readonly Leq: "LEQ";
  readonly In: "IN";
  readonly HasPart: "HAS_PART";
  readonly IsA: "IS_A";
  readonly IsAllOf: "IS_ALL_OF";
  readonly IsAnyOf: "IS_ANY_OF";
  readonly IsNoneOf: "IS_NONE_OF";
};
/**
 * Supported Types of values for the right hand side of an expression
 * @export
 */
export declare const UiPolicyLiteralType: {
  readonly String: "STRING";
  readonly StringList: "STRING_LIST";
  readonly Json: "JSON";
};

export declare type UiPolicyLiteralType = (typeof UiPolicyLiteralType)[keyof typeof UiPolicyLiteralType];
/**
 * Sum type: A String, a list of Strings or a generic JSON value.
 * @export
 * @interface UiPolicyLiteral
 */
export declare interface UiPolicyLiteral {
  /**
   *
   * @type {UiPolicyLiteralType}
   * @memberof UiPolicyLiteral
   */
  type: UiPolicyLiteralType;
  /**
   * Only for types STRING and JSON
   * @type {string}
   * @memberof UiPolicyLiteral
   */
  value?: string;
  /**
   * Only for type STRING_LIST
   * @type {Array<string>}
   * @memberof UiPolicyLiteral
   */
  valueList?: Array<string>;
}

export declare type OperatorDto = (typeof OperatorDto)[keyof typeof OperatorDto];
/**
 * ODRL AtomicConstraint as supported by the sovity product landscape. For example 'a EQ b', 'c IN [d, e, f]'
 * @export
 * @interface UiPolicyConstraint
 */
export declare interface UiPolicyConstraint {
  /**
   * Left side of the expression.
   * @type {string}
   * @memberof UiPolicyConstraint
   */
  left: string;
  /**
   *
   * @type {OperatorDto}
   * @memberof UiPolicyConstraint
   */
  operator: OperatorDto;
  /**
   *
   * @type {UiPolicyLiteral}
   * @memberof UiPolicyConstraint
   */
  right: UiPolicyLiteral;
}
