
import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { PolicyViewComponent } from './policy-view/policy-view.component';
import { NewPolicyComponent } from './new-policy/new-policy.component';

const routes: Routes = [
  { path: '', component: PolicyViewComponent },
  { path: 'create', component: NewPolicyComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class PoliciesRoutingModule { }
