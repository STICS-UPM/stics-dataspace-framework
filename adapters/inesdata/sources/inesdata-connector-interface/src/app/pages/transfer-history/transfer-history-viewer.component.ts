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

  columns: string[] = ['state', 'lastUpdated', 'assetId', 'contractId', 'validation'];
  transferProcesses: TransferProcess[];
  storageExplorerLinkTemplate: string | undefined;

  private static readonly VALIDATION_KEY_PREFIX = 'inesdata.rdf.validation.';

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

  /**
   * After {@code expandArray} / JSON-LD handling, validation fields may be plain strings or
   * wrapped objects ({@value}, nested arrays). Avoid String(object) → "[object Object]" in the table.
   */
  private validationValueToString(raw: unknown): string {
    if (raw == null) {
      return '';
    }
    if (typeof raw === 'string') {
      return raw.trim();
    }
    if (typeof raw === 'number' || typeof raw === 'boolean') {
      return String(raw);
    }
    if (Array.isArray(raw)) {
      return raw.map((x) => this.validationValueToString(x)).filter((s) => s.length > 0).join(', ');
    }
    if (typeof raw === 'object') {
      const o = raw as Record<string, unknown>;
      if ('@value' in o) {
        return this.validationValueToString(o['@value']);
      }
      if ('value' in o) {
        return this.validationValueToString(o['value']);
      }
      if ('@list' in o && Array.isArray(o['@list'])) {
        return this.validationValueToString(o['@list']);
      }
      try {
        return JSON.stringify(o);
      } catch {
        return '';
      }
    }
    return String(raw).trim();
  }

  private getValidationProp(item: any, suffix: string): string {
    const pp = item?.privateProperties;
    if (!pp) {
      return '';
    }
    const key = TransferHistoryViewerComponent.VALIDATION_KEY_PREFIX + suffix;
    const value = pp[key]
      ?? pp['https://w3id.org/edc/v0.0.1/ns/' + key]
      ?? pp['edc:' + key];
    return this.validationValueToString(value);
  }

  getValidationStatus(item: any): string {
    return this.getValidationProp(item, 'status').toUpperCase();
  }

  getValidationDisplay(item: any): string {
    const status = this.getValidationStatus(item);
    if (!status) {
      return 'N/A';
    }
    if (status === 'SUCCESS') {
      return 'SUCCESS';
    }
    const message = this.getValidationProp(item, 'message');
    const errors = this.getValidationProp(item, 'errors');
    const parts: string[] = [];
    if (message) {
      parts.push(`message="${message}"`);
    }
    if (errors) {
      parts.push(`errors=[${errors}]`);
    }
    return parts.length ? parts.join(' ') : status;
  }

  getValidationCssClass(item: any): string {
    const status = this.getValidationStatus(item);
    if (!status) {
      return 'validation-na';
    }
    if (status === 'SUCCESS') {
      return 'validation-success';
    }
    if (status === 'SKIPPED') {
      return 'validation-skipped';
    }
    return 'validation-failed';
  }
}
