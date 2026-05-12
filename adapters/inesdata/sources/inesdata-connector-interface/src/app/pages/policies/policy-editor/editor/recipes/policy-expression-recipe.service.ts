import {ComponentType} from '@angular/cdk/portal';
import {Injectable} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {Observable} from 'rxjs';
import {TimespanRestrictionDialogComponent} from './timespan-restriction-dialog/timespan-restriction-dialog.component';
import { UiPolicyExpression } from '../../../../../shared/models/policy/ui-policy-expression';
import { showDialogUntil } from 'src/app/shared/utils/mat-dialog-utils';
import { filterNotNull } from 'src/app/shared/utils/rxjs-utils';

export interface PolicyExpressionRecipe {
  title: string;
  onclick: (until$: Observable<any>) => Observable<UiPolicyExpression>;
}

@Injectable()
export class PolicyExpressionRecipeService {
  recipes: PolicyExpressionRecipe[] = [
    {
      title: 'Timespan Restriction',
      onclick: (until$: Observable<any>) =>
        this.showRecipeDialog(TimespanRestrictionDialogComponent, until$),
    },
  ];

  constructor(private dialog: MatDialog) {}

  private showRecipeDialog(
    cmp: ComponentType<any>,
    until$: Observable<any>,
  ): Observable<UiPolicyExpression> {
    return showDialogUntil<unknown, UiPolicyExpression>(
      this.dialog,
      cmp,
      {},
      until$,
    ).pipe(filterNotNull());
  }
}
