import { NgModule } from '@angular/core';
import {PoliciesRoutingModule} from "./policies-routing.module"

import { PolicyRuleViewerComponent } from './policy-rule-viewer/policy-rule-viewer.component';
import { PolicyViewComponent } from './policy-view/policy-view.component';
import { SharedModule } from 'src/app/shared/shared.module';
import { PolicyEditorModule } from './policy-editor/policy-editor.module';
import { PolicyDefinitionCreatePageForm } from './new-policy/policy-definition-create-page-form';
import { ExpressionFormControls } from './policy-editor/editor/expression-form-controls';
import { ExpressionFormHandler } from './policy-editor/editor/expression-form-handler';
import {JsonDialogModule} from '../json-dialog/json-dialog.module';
import { NewPolicyComponent } from './new-policy/new-policy.component';

@NgModule({
  declarations: [
    PolicyRuleViewerComponent,
    PolicyViewComponent,
    NewPolicyComponent
  ],
  providers: [
    PolicyDefinitionCreatePageForm,
    ExpressionFormControls,
    ExpressionFormHandler
  ],
  imports: [
    PoliciesRoutingModule,
    SharedModule,
    PolicyEditorModule,
    JsonDialogModule
  ]
})
export class PoliciesModule { }
