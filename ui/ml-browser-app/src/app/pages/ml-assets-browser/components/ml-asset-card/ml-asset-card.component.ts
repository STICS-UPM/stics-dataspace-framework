import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';

import { MLAsset } from '../../../../shared/models/ml-asset';

@Component({
  selector: 'app-ml-asset-card',
  standalone: true,
  imports: [
    CommonModule,
    MatIconModule,
    MatButtonModule,
    MatCardModule,
    MatChipsModule
  ],
  templateUrl: './ml-asset-card.component.html',
  styleUrl: './ml-asset-card.component.scss'
})
export class MlAssetCardComponent {
  @Input() asset!: MLAsset;
  @Output() viewDetails = new EventEmitter<MLAsset>();
  @Output() downloadAsset = new EventEmitter<MLAsset>();
  @Output() createContract = new EventEmitter<MLAsset>();
  @Output() negotiate = new EventEmitter<MLAsset>();
  metadataExpanded = false;

  onViewDetails(): void {
    this.viewDetails.emit(this.asset);
  }

  onDownload(): void {
    this.downloadAsset.emit(this.asset);
  }

  onCreateContract(): void {
    this.createContract.emit(this.asset);
  }

  onNegotiate(): void {
    this.negotiate.emit(this.asset);
  }

  /**
   * Contract button action: CREATE CONTRACT for local assets, NEGOTIATE for external
   */
  onContractAction(): void {
    if (!this.isLocalAsset() && this.asset.hasAgreement) {
      return;
    }
    if (!this.isLocalAsset() && this.asset.negotiationInProgress) {
      return;
    }
    if (this.isLocalAsset()) {
      this.onCreateContract();
    } else {
      this.onNegotiate();
    }
  }

  /**
   * Determine whether the asset is local or external.
   * Use isLocal if available, otherwise check originator.
   */
  isLocalAsset(): boolean {
    // If backend provided isLocal, use it
    if (this.asset.isLocal !== undefined) {
      return this.asset.isLocal;
    }
    // Fallback to originator check
    return this.asset.originator === 'Local Connector';
  }

  getViewDetailsButtonText(): string {
    return this.asset.hasContractOffers 
      ? 'View Details and Contract Offers' 
      : 'View Details';
  }

  getTruncatedDescription(text: string, maxLength = 100): string {
    if (!text) return '';
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
  }

  get displayKeywords(): string[] {
    return this.asset.keywords.slice(0, 5);
  }

  get hasMoreKeywords(): boolean {
    return this.asset.keywords.length > 5;
  }

  get keywordCount(): number {
    return this.asset.keywords.length;
  }

  getContractActionIcon(): string {
    if (this.isLocalAsset()) {
      return 'description';
    }
    if (this.asset.negotiationInProgress) {
      return 'hourglass_top';
    }
    if (this.asset.hasAgreement) {
      return 'check_circle';
    }
    return 'handshake';
  }

  getContractActionText(): string {
    if (this.isLocalAsset()) {
      return 'Create Contract';
    }
    if (this.asset.negotiationInProgress) {
      return 'Negotiating...';
    }
    if (this.asset.hasAgreement) {
      return 'Negotiated';
    }
    return 'Negotiate';
  }

  get modelMetadataChips(): string[] {
    const chips: string[] = [];
    const add = (label: string, value?: string) => {
      const normalized = (value || '').trim();
      if (normalized) {
        chips.push(`${label}: ${normalized}`);
      }
    };

    add('Task', this.asset.tasks?.[0]);
    add('Subtask', this.asset.subtasks?.[0]);
    add('Algorithm', this.asset.algorithms?.[0]);
    add('Library', this.asset.libraries?.[0]);
    add('Framework', this.asset.frameworks?.[0]);
    add('Format', this.asset.format);
    add('Storage', this.asset.storageType);
    add('Content', this.asset.contentType);

    return Array.from(new Set(chips)).slice(0, 6);
  }

  toggleMetadata(): void {
    this.metadataExpanded = !this.metadataExpanded;
  }
}
