import { UiPolicyExpressionType } from "./ui-policy-expression-type";

export interface PolicyMultiExpressionConfig {
  expressionType: UiPolicyExpressionType;
  title: string;
  description: string;
}

export const SUPPORTED_MULTI_EXPRESSIONS: PolicyMultiExpressionConfig[] = [
  {
    expressionType: 'AND',
    title: 'AND',
    description:
      'Conjunction of several expressions. Evaluates to true if and only if all child expressions are true',
  },
  {
    expressionType: 'OR',
    title: 'OR',
    description:
      'Disjunction of several expressions. Evaluates to true if and only if at least one child expression is true',
  }
];
