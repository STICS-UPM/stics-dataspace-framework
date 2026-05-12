import { NgModule } from '@angular/core';
import { ContractsRoutingModule } from './contracts-routing.module';

import { ContractViewerComponent } from './contract-viewer/contract-viewer.component';
import { ContractTransferDialog } from './contract-transfer-dialog/contract-transfer-dialog.component';
import { SharedModule } from 'src/app/shared/shared.module';

@NgModule({
  declarations: [
    ContractViewerComponent,
    ContractTransferDialog
  ],
  imports: [
    ContractsRoutingModule,
    SharedModule
  ]
})
export class ContractsModule { }
