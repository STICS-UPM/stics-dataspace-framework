import { NgModule } from '@angular/core';
import { TransferHistoryRoutingModule } from './transfer-history-routing.module'
import { TransferHistoryViewerComponent } from './transfer-history-viewer.component';
import { SharedModule } from 'src/app/shared/shared.module';

@NgModule({
  declarations: [
    TransferHistoryViewerComponent
  ],
  imports: [
    TransferHistoryRoutingModule,
    SharedModule
  ]
})
export class TransferHistoryModule { }
