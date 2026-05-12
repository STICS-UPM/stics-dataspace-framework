import { OperatorDto } from "./ui-policy-constraint";
import { UiPolicyExpression } from "./ui-policy-expression";
import { UiPolicyExpressionType } from "./ui-policy-expression-type";


export const constraint = (
  left: string,
  operator: OperatorDto,
  value: string,
): UiPolicyExpression => ({
  type: 'CONSTRAINT',
  constraint: {
    left,
    operator,
    right: {type: 'STRING', value},
  },
});

export const constraintList = (
  left: string,
  operator: OperatorDto,
  valueList: string[],
): UiPolicyExpression => ({
  type: 'CONSTRAINT',
  constraint: {
    left,
    operator,
    right: {type: 'STRING_LIST', valueList},
  },
});

export const multi = (
  type: Exclude<UiPolicyExpressionType, 'EMPTY' | 'CONSTRAINT'>,
  ...expressions: UiPolicyExpression[]
): UiPolicyExpression => ({
  type,
  expressions,
});
