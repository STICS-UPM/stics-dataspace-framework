
import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { AssetViewerComponent } from './asset-viewer/asset-viewer.component';
import { AssetCreateComponent } from './asset-create/asset-create.component';
import { ContractOffersViewerComponent } from '../catalog/contract-offers-viewer/contract-offers-viewer.component';

const routes: Routes = [
  { path: '', component: AssetViewerComponent },
  { path: 'create', component: AssetCreateComponent },
  { path: 'view', component: ContractOffersViewerComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AssetsRoutingModule { }
