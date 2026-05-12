
import {PolicyMultiExpressionConfig} from './policy-multi-expressions';
import {PolicyOperatorConfig} from './policy-operators';
import {PolicyVerbConfig} from './policy-verbs';
import { UiPolicyLiteral } from './ui-policy-constraint';

export interface PolicyExpressionMapped {
  type: 'CONSTRAINT' | 'MULTI' | 'EMPTY';

  multiExpression?: PolicyMultiExpressionConfig;
  expressions?: PolicyExpressionMapped[];

  verb?: PolicyVerbConfig;
  operator?: PolicyOperatorConfig;
  valueRaw?: UiPolicyLiteral;
  valueJson?: string;
  displayValue?: string;
}
