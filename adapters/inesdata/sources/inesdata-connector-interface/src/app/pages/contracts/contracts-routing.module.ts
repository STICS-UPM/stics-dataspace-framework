
import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { ContractViewerComponent } from './contract-viewer/contract-viewer.component';

const routes: Routes = [
  { path: '', component: ContractViewerComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class ContractsRoutingModule { }
