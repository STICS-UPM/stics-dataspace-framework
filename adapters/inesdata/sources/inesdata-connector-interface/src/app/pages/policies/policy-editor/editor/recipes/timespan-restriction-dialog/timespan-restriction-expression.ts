
import {policyLeftExpressions} from '../../../../../../shared/models/policy/policy-left-expressions';
import {constraint, multi} from '../../../../../../shared/models/policy/ui-policy-expression-utils';
import { UiPolicyExpression } from '../../../../../../shared/models/policy/ui-policy-expression';
import { OperatorDto } from '../../../../../../shared/models/policy/ui-policy-constraint';
import { adjustDate } from '../../../../../../shared/utils/date-utils';

export const buildTimespanRestriction = (
  firstDay: Date,
  lastDay: Date,
): UiPolicyExpression => {
  const evaluationTimeConstraint = (operator: OperatorDto, value: Date) =>
    constraint(
      policyLeftExpressions.policyEvaluationTime,
      operator,
      adjustDate(value, operator),
    );

  return multi(
    'AND',
    evaluationTimeConstraint('GEQ', firstDay),
    evaluationTimeConstraint('LEQ', lastDay),
  );
};
