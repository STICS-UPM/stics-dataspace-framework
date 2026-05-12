
import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { ContractDefinitionViewerComponent } from './contract-definition-viewer/contract-definition-viewer.component';
import { ContractDefinitionNewComponent } from './contract-definition-new/contract-definition-new.component';

const routes: Routes = [
  { path: '', component: ContractDefinitionViewerComponent },
  { path: 'create', component: ContractDefinitionNewComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class ContractDefinitonsRoutingModule { }
