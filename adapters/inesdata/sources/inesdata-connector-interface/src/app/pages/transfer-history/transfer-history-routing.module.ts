
import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { TransferHistoryViewerComponent } from './transfer-history-viewer.component';

const routes: Routes = [
  { path: '', component: TransferHistoryViewerComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class TransferHistoryRoutingModule { }
