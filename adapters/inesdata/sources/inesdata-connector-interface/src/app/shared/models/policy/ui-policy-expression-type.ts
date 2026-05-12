/**
 * Ui Policy Expression types:
 * * `CONSTRAINT` - Expression 'a=b'
 * * `AND` - Conjunction of several expressions. Evaluates to true iff all child expressions are true.
 * * `OR` - Disjunction of several expressions. Evaluates to true iff at least one child expression is true.
 * @export
 */
export declare const UiPolicyExpressionType: {
  readonly Empty: "EMPTY";
  readonly Constraint: "CONSTRAINT";
  readonly And: "AND";
  readonly Or: "OR";
};

export declare type UiPolicyExpressionType = (typeof UiPolicyExpressionType)[keyof typeof UiPolicyExpressionType];
