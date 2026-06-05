/*
 *  Copyright (c) 2025 Fraunhofer-Gesellschaft zur Förderung der angewandten Forschung e.V.
 *
 *  This program and the accompanying materials are made available under the
 *  terms of the Apache License, Version 2.0 which is available at
 *  https://www.apache.org/licenses/LICENSE-2.0
 *
 *  SPDX-License-Identifier: Apache-2.0
 *
 *  Contributors:
 *       Fraunhofer-Gesellschaft zur Förderung der angewandten Forschung e.V. - initial API and implementation
 *
 */

import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges, inject } from '@angular/core';

import { TransferProcess, TransferProcessStates } from '@think-it-labs/edc-connector-client';
import { DatePipe, NgClass } from '@angular/common';
import { TransferHistoryDetailsComponent } from '../transfer-history-details/transfer-history-details.component';
import { DeleteConfirmComponent, ModalAndAlertService } from '@eclipse-edc/dashboard-core';

@Component({
  selector: 'lib-transfer-history-table',
  standalone: true,
  imports: [NgClass, DatePipe],
  templateUrl: './transfer-history-table.component.html',
})
export class TransferHistoryTableComponent implements OnChanges {
  private readonly modalAndAlertService = inject(ModalAndAlertService);

  private static readonly VALIDATION_KEY_PREFIX = 'edc.rdf.validation.';
  private static readonly LEGACY_VALIDATION_KEY_PREFIX = 'inesdata.rdf.validation.';

  @Input() transferProcesses: TransferProcess[] | null = [];
  @Output() deprovisionEvent = new EventEmitter<TransferProcess>();

  validStates = new Set<string>([
    TransferProcessStates.INITIAL,
    TransferProcessStates.PROVISIONED,
    TransferProcessStates.REQUESTED,
    TransferProcessStates.STARTED,
    TransferProcessStates.COMPLETED,
  ]);

  exceptionStates = new Set<string>([TransferProcessStates.SUSPENDED, TransferProcessStates.TERMINATED]);

  stateType: Record<string, string> = {};

  async ngOnChanges(changes: SimpleChanges) {
    if (changes['transferProcesses']) {
      if (this.transferProcesses) {
        for (const transferProcess of this.transferProcesses) {
          if (transferProcess.id) {
            this.stateType[transferProcess.id] = this.getStateType(transferProcess.state);
          }
        }
      }
    }
  }

  private getStateType(state: string) {
    if (this.validStates.has(state)) {
      return 'okay';
    } else if (this.exceptionStates.has(state)) {
      return 'error';
    } else {
      return 'neutral';
    }
  }

  openDetails(transferProcess: TransferProcess) {
    this.modalAndAlertService.openModal(TransferHistoryDetailsComponent, {
      transferProcess: transferProcess,
      stateType: this.stateType[transferProcess.id],
    });
  }

  deprovision(transferProcess: TransferProcess) {
    this.modalAndAlertService.openModal(
      DeleteConfirmComponent,
      {
        customText: `Do you really want to request the deprovisioning of transfer process '${transferProcess.id}'?`,
      },
      {
        canceled: () => this.modalAndAlertService.closeModal(),
        confirm: () => {
          this.modalAndAlertService.closeModal();
          this.deprovisionEvent.emit(transferProcess);
        },
      },
    );
  }

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
      return raw.map(x => this.validationValueToString(x)).filter(s => s.length > 0).join(', ');
    }
    if (typeof raw === 'object') {
      const o = raw as Record<string, unknown>;
      if ('@value' in o) {
        return this.validationValueToString(o['@value']);
      }
      if ('value' in o) {
        return this.validationValueToString(o['value']);
      }
      try {
        return JSON.stringify(o);
      } catch {
        return '';
      }
    }
    return String(raw).trim();
  }

  private getValidationProp(item: TransferProcess, suffix: string): string {
    const pp = (item as unknown as { privateProperties?: Record<string, unknown> }).privateProperties;
    if (!pp) {
      return '';
    }
    const keys = [
      TransferHistoryTableComponent.VALIDATION_KEY_PREFIX + suffix,
      TransferHistoryTableComponent.LEGACY_VALIDATION_KEY_PREFIX + suffix,
    ];
    for (const key of keys) {
      const value = pp[key] ?? pp['https://w3id.org/edc/v0.0.1/ns/' + key] ?? pp['edc:' + key];
      const normalized = this.validationValueToString(value);
      if (normalized) {
        return normalized;
      }
    }
    return '';
  }

  getValidationDisplay(transferProcess: TransferProcess): string {
    const status = this.getValidationProp(transferProcess, 'status').toUpperCase();
    if (!status) {
      return 'N/A';
    }
    if (status === 'SUCCESS') {
      return 'SUCCESS';
    }
    const message = this.getValidationProp(transferProcess, 'message');
    const errors = this.getValidationProp(transferProcess, 'errors');
    const parts: string[] = [];
    if (message) {
      parts.push(`message="${message}"`);
    }
    if (errors) {
      parts.push(`errors=[${errors}]`);
    }
    return parts.length ? parts.join(' ') : status;
  }

  getValidationBadgeClass(transferProcess: TransferProcess): string {
    const status = this.getValidationProp(transferProcess, 'status').toUpperCase();
    if (!status) {
      return 'badge-neutral';
    }
    if (status === 'SUCCESS') {
      return 'badge-success';
    }
    if (status === 'SKIPPED') {
      return 'badge-warning';
    }
    return 'badge-error';
  }
}
