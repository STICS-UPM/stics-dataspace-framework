
import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { CatalogBrowserComponent } from './catalog-browser/catalog-browser.component';
import { ContractOffersViewerComponent } from './contract-offers-viewer/contract-offers-viewer.component';

const routes: Routes = [
  { path: '', component: CatalogBrowserComponent },
  { path: 'datasets/view', component: ContractOffersViewerComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class CatalogRoutingModule { }
