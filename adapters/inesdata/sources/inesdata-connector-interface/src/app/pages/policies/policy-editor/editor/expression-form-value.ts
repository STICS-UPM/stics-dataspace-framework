import {PolicyMultiExpressionConfig} from '../../../../shared/models/policy/policy-multi-expressions';
import {PolicyOperatorConfig} from '../../../../shared/models/policy/policy-operators';
import {PolicyVerbConfig} from '../../../../shared/models/policy/policy-verbs';

export interface ExpressionFormValue {
  type: 'CONSTRAINT' | 'MULTI' | 'EMPTY';

  multiExpression?: PolicyMultiExpressionConfig;
  verb?: PolicyVerbConfig;
  supportedOperators?: PolicyOperatorConfig[];
}
