import { Component, OnDestroy, OnInit } from '@angular/core';
import { NotificationService } from 'src/app/shared/services/notification.service';
import { PolicyDefinitionCreatePageForm } from './policy-definition-create-page-form';
import { ExpressionFormHandler } from '../policy-editor/editor/expression-form-handler';
import { ValidationMessages } from 'src/app/shared/validators/validation-messages';
import { Subject } from 'rxjs';
import { PolicyDefinitionCreateDto } from '../../../shared/models/policy/policy-definition-create-dto';
import { PolicyService } from 'src/app/shared/services/policy.service';
import { IdResponse } from '@think-it-labs/edc-connector-client';
import { Observer } from '@jsonforms/core';
import { Router } from '@angular/router';

@Component({
  selector: 'app-new-policy',
  templateUrl: './new-policy.component.html',
  styleUrls: ['./new-policy.component.scss']
})
export class NewPolicyComponent  implements OnInit,OnDestroy {

  private readonly errorOrUpdateSubscriber: Observer<IdResponse>;

  constructor(
    public form: PolicyDefinitionCreatePageForm,
    public expressionFormHandler: ExpressionFormHandler,
    public validationMessages: ValidationMessages,
    private notificationService: NotificationService,
    private policyService: PolicyService,
    private router: Router
  ) {

  }

  ngOnInit(): void {

    this.expressionFormHandler.reset()
    this.form.reset()
  }

  onSave() {
    const createDto = this.buildPolicyDefinitionCreateDto();
    if(this.form.group.valid){
        if (createDto) {
          this.policyService.createComplexPolicy(createDto).subscribe(
            {
              next: (response: IdResponse) => this.errorOrUpdateSubscriber.next(response),
              error: (error: Error) => this.showError(error, "An error occurred while creating the policy."),
              complete: () => {
                this.navigateToPolicies()
                this.notificationService.showInfo("Successfully created");
              }
            }
          );
      }
    }
  }

  buildPolicyDefinitionCreateDto(): PolicyDefinitionCreateDto {
    return {
      policyDefinitionId: this.form.group.controls.id.value,
      expression: this.expressionFormHandler.toUiPolicyExpression(),
    };
  }

  ngOnDestroy$ = new Subject();

  ngOnDestroy(): void {
    this.ngOnDestroy$.next(null);
    this.ngOnDestroy$.complete();
  }


  private showError(error: Error, errorMessage: string) {
    console.error(error);
    this.notificationService.showError(errorMessage);
  }

  navigateToPolicies(){
    this.router.navigate(['policies'])
  }
}
