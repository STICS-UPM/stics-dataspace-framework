import {Component, OnDestroy} from '@angular/core';
import {FormBuilder} from '@angular/forms';
import {MatDialogRef} from '@angular/material/dialog';
import {Subject} from 'rxjs';
import {buildTimespanRestriction} from './timespan-restriction-expression';
import { UiPolicyExpression } from '../../../../../../shared/models/policy/ui-policy-expression';
import { ValidationMessages } from 'src/app/shared/validators/validation-messages';
import { validDateRange } from 'src/app/shared/validators/valid-date-range-optional-end';

@Component({
  selector: 'timespan-restriction-dialog',
  templateUrl: './timespan-restriction-dialog.component.html',
  styleUrls: ['./timespan-restriction-dialog.component.scss']
})
export class TimespanRestrictionDialogComponent implements OnDestroy {
  group = this.formBuilder.nonNullable.group({
    range: this.formBuilder.group(
      {
        start: null as Date | null,
        end: null as Date | null,
      },
      {validators: validDateRange},
    ),
  });

  constructor(
    private formBuilder: FormBuilder,
    private dialogRef: MatDialogRef<TimespanRestrictionDialogComponent>,
    public validationMessages: ValidationMessages,
  ) {
    dialogRef.disableClose = true;
  }

  onAdd() {
    const formValue = this.group.value;

    const expression = buildTimespanRestriction(
      formValue.range!.start!,
      formValue.range!.end!,
    );

    this.close(expression);
  }

  private close(params: UiPolicyExpression) {
    this.dialogRef.close(params);
  }

  ngOnDestroy$ = new Subject();

  ngOnDestroy(): void {
    this.ngOnDestroy$.next(null);
    this.ngOnDestroy$.complete();
  }
}
