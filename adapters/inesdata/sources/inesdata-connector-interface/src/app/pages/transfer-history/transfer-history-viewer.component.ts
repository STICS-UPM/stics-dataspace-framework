import { environment } from 'src/environments/environment';
import { Component, OnInit } from '@angular/core';
import { TransferProcessService } from "../../shared/services/transferProcess.service";
import { QuerySpec, TransferProcess } from "../../shared/models/edc-connector-entities";
import { ConfirmationDialogComponent, ConfirmDialogModel } from "../../shared/components/confirmation-dialog/confirmation-dialog.component";
import { MatDialog } from "@angular/material/dialog";
import { PageEvent } from '@angular/material/paginator';

@Component({
  selector: 'app-transfer-history',
  templateUrl: './transfer-history-viewer.component.html',
  styleUrls: ['./transfer-history-viewer.component.scss']
})
export class TransferHistoryViewerComponent implements OnInit {

  columns: string[] = ['state', 'lastUpdated', 'assetId', 'contractId'];
  transferProcesses: TransferProcess[];
  storageExplorerLinkTemplate: string | undefined;

  // Pagination
  pageSize = 10;
  currentPage = 0;
  paginatorLength = 0;

  constructor(private transferProcessService: TransferProcessService,
    private dialog: MatDialog) {
  }

  ngOnInit(): void {
    this.countTransferProcesses();
    this.loadTransferProcesses(this.currentPage);
    this.storageExplorerLinkTemplate = environment.runtime.storageExplorerLinkTemplate
  }

  loadTransferProcesses(offset: number) {
    const querySpec: QuerySpec = {
      offset: offset,
      limit: this.pageSize
    }

    this.transferProcessService.queryAllTransferProcesses(querySpec)
      .subscribe(results => {
        this.transferProcesses = results;
      });
  }

  countTransferProcesses() {
    this.transferProcessService.count()
      .subscribe(result => {
        this.paginatorLength = result;
      });
  }

  asDate(epochMillis?: number) {
    return epochMillis ? new Date(epochMillis).toLocaleDateString() : '';
  }

  changePage(event: PageEvent) {
    const offset = event.pageIndex * event.pageSize;
    this.pageSize = event.pageSize;
    this.currentPage = event.pageIndex;
    this.loadTransferProcesses(offset);
  }

  refresh(){
    this.currentPage = 0;
    this.countTransferProcesses();
    this.loadTransferProcesses(0);
  }
}
