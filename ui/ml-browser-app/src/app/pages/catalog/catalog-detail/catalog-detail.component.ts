import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { MatListModule } from '@angular/material/list';
import { MatChipsModule } from '@angular/material/chips';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { CatalogStateService } from '../../../shared/services/catalog-state.service';
import { ContractNegotiationService } from '../../../shared/services/contract-negotiation.service';
import { ConnectorContextService } from '../../../shared/services/connector-context.service';
import { NotificationService } from '../../../shared/services/notification.service';
import { ContractDefinitionService } from '../../../shared/services/contract-definition.service';
import { environment } from '../../../../environments/environment';

interface ContractOffer {
  '@id': string;
  '@type': string;
  contractId: string;
  accessPolicyId: string;
  contractPolicyId: string;
  accessPolicy: any;
  contractPolicy: any;
  hasAgreement?: boolean;
  negotiationInProgress?: boolean;
  policyIdsResolved?: boolean;
}

interface CatalogDetailData {
  assetId: string;
  properties: any;
  originator: string;
  contractOffers: ContractOffer[];
  contractCount: number;
  catalogView?: boolean;
  returnUrl?: string;
  selectedTabIndex?: number;
}

/**
 * Catalog Detail Component
 * Shows asset information and contract offers for negotiation
 * Similar to dataspace-connector-interface contract-offers-viewer
 */
@Component({
  selector: 'app-catalog-detail',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatTabsModule,
    MatListModule,
    MatChipsModule,
    MatExpansionModule,
    MatProgressBarModule
  ],
  templateUrl: './catalog-detail.component.html',
  styleUrl: './catalog-detail.component.scss'
})
export class CatalogDetailComponent implements OnInit {
  private router = inject(Router);
  private catalogStateService = inject(CatalogStateService);
  private contractNegotiationService = inject(ContractNegotiationService);
  private connectorContextService = inject(ConnectorContextService);
  private notificationService = inject(NotificationService);
  private contractDefinitionService = inject(ContractDefinitionService);

  data: CatalogDetailData | null = null;
  selectedTabIndex = 0;
  private readonly negotiationPollDelayMs = 2000;
  private readonly negotiationPollMaxAttempts = 30;

  ngOnInit(): void {
    console.log('[Catalog Detail] Component initialized');
    
    // Get data from service
    this.data = this.catalogStateService.getCurrentItem();
    console.log('[Catalog Detail] Data from service:', this.data);

    // Check if we have the required data
    if (!this.data || !this.data.assetId) {
      console.error('[Catalog Detail] No data available, redirecting to catalog');
      this.router.navigate(['/catalog']);
      return;
    }

    // Set selected tab index if provided
    if (this.data.selectedTabIndex !== undefined) {
      this.selectedTabIndex = this.data.selectedTabIndex;
      console.log('[Catalog Detail] Tab index set to:', this.selectedTabIndex);
    }

    this.data.contractOffers = this.normalizeContractOffers(this.data.contractOffers || []);
    this.enrichPolicyIdsFromContractDefinitions();
    this.syncAgreementStatus();

    console.log('[Catalog Detail] Successfully loaded data for asset:', this.data.assetId);
  }

  backToList(): void {
    const returnUrl = this.data?.returnUrl || '/catalog';
    this.router.navigate([returnUrl]);
  }

  getPolicyAction(policy: any): string {
    const policyData = policy?.policy || policy;
    if (!policyData) return 'N/A';
    const permissionsRaw = policyData['odrl:permission'];
    const permissions = Array.isArray(permissionsRaw) ? permissionsRaw : (permissionsRaw ? [permissionsRaw] : []);
    if (permissions.length > 0) {
      return permissions[0]['odrl:action'] || 'N/A';
    }
    return 'N/A';
  }

  getPolicyConstraints(policy: any): any[] {
    const policyData = policy?.policy || policy;
    if (!policyData) return [];
    const permissionsRaw = policyData['odrl:permission'];
    const permissions = Array.isArray(permissionsRaw) ? permissionsRaw : (permissionsRaw ? [permissionsRaw] : []);
    if (permissions.length > 0) {
      const constraintsRaw = permissions[0]['odrl:constraint'];
      return Array.isArray(constraintsRaw) ? constraintsRaw : (constraintsRaw ? [constraintsRaw] : []);
    }
    return [];
  }

  getPolicyObligations(policy: any): any[] {
    const policyData = policy?.policy || policy;
    if (!policyData) return [];
    const obligationsRaw = policyData['odrl:obligation'];
    return Array.isArray(obligationsRaw) ? obligationsRaw : (obligationsRaw ? [obligationsRaw] : []);
  }

  getPolicyProhibitions(policy: any): any[] {
    const policyData = policy?.policy || policy;
    if (!policyData) return [];
    const prohibitionsRaw = policyData['odrl:prohibition'];
    return Array.isArray(prohibitionsRaw) ? prohibitionsRaw : (prohibitionsRaw ? [prohibitionsRaw] : []);
  }

  formatConstraint(constraint: any): string {
    const leftOperand = constraint['odrl:leftOperand'] || '';
    const operator = constraint['odrl:operator'] || '';
    const rightOperand = constraint['odrl:rightOperand'] || '';
    return `${leftOperand} ${operator} ${rightOperand}`;
  }

  viewPolicyJson(policy: any): void {
    const payload = policy?.contractPolicy?.policy || policy?.contractPolicy || policy?.accessPolicy?.policy || policy?.accessPolicy || policy;
    const pretty = JSON.stringify(payload, null, 2);
    const popup = window.open('', '_blank', 'noopener,noreferrer,width=900,height=700');
    if (!popup) {
      this.notificationService.showWarning('Popup blocked. Allow popups to view JSON-LD.');
      return;
    }
    popup.document.write(`<html><head><title>Policy JSON-LD</title></head><body><pre>${this.escapeHtml(pretty)}</pre></body></html>`);
    popup.document.close();
  }

  negotiateContract(offer: ContractOffer): void {
    if (!this.data) {
      return;
    }
    if (offer.hasAgreement) {
      this.notificationService.showInfo('This asset is already negotiated.');
      return;
    }
    if (offer.negotiationInProgress) {
      this.notificationService.showInfo('Negotiation already in progress.');
      return;
    }

    offer.negotiationInProgress = true;
    const request = {
      '@type': 'ContractRequest',
      counterPartyAddress: this.connectorContextService.getCounterPartyProtocolUrl(),
      protocol: environment.runtime.catalogProtocol,
      policy: {
        '@context': 'http://www.w3.org/ns/odrl.jsonld',
        '@id': offer.contractId || offer['@id'],
        '@type': 'Offer',
        assigner: this.extractAssigner(),
        target: this.data.assetId
      }
    };

    this.contractNegotiationService.initiate(request).subscribe({
      next: (result) => {
        const negotiationId = result?.['@id'] || result?.id || '';
        this.notificationService.showInfo(`Contract negotiation started: ${negotiationId || 'created'}`);
        if (negotiationId) {
          this.pollNegotiationStatus(String(negotiationId), offer, this.negotiationPollMaxAttempts);
        } else {
          offer.negotiationInProgress = false;
          this.syncAgreementStatus();
        }
      },
      error: (error) => {
        offer.negotiationInProgress = false;
        const msg = error?.error?.message || error?.message || 'Unknown error';
        this.notificationService.showError(`Failed to negotiate contract: ${msg}`);
      }
    });
  }

  getPropertyKeys(): string[] {
    if (!this.data?.properties) return [];
    return Object.keys(this.data.properties).filter(key => 
      !['name', 'version', 'contentType', 'description', 'shortDescription', 
        'keywords', 'byteSize', 'format', 'type', 'owner'].includes(key)
    );
  }

  isArray(value: any): boolean {
    return Array.isArray(value);
  }

  isObject(value: any): boolean {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  getEntries(obj: any): { key: string; value: any }[] {
    if (!obj || typeof obj !== 'object') return [];
    return Object.entries(obj).map(([key, value]) => ({ key, value }));
  }

  private normalizeContractOffers(rawOffers: any[]): ContractOffer[] {
    return (rawOffers || []).map((raw) => {
      const rawPolicy = raw?.policy || raw;
      const id = String(raw?.contractId || raw?.['@id'] || rawPolicy?.['@id'] || '');
      return {
        '@id': String(raw?.['@id'] || rawPolicy?.['@id'] || id),
        '@type': String(raw?.['@type'] || rawPolicy?.['@type'] || 'odrl:Offer'),
        contractId: id,
        accessPolicyId: String(raw?.accessPolicyId || raw?.['edc:accessPolicyId'] || ''),
        contractPolicyId: String(raw?.contractPolicyId || raw?.['edc:contractPolicyId'] || ''),
        accessPolicy: raw?.accessPolicy || { policy: rawPolicy },
        contractPolicy: raw?.contractPolicy || { policy: rawPolicy },
        hasAgreement: false,
        negotiationInProgress: false,
        policyIdsResolved: !!(raw?.accessPolicyId || raw?.['edc:accessPolicyId'] || raw?.contractPolicyId || raw?.['edc:contractPolicyId'])
      };
    });
  }

  private enrichPolicyIdsFromContractDefinitions(): void {
    if (!this.data) {
      return;
    }

    const hasMissingPolicyIds = (this.data.contractOffers || []).some(
      (offer) => !offer.accessPolicyId || !offer.contractPolicyId
    );
    if (!hasMissingPolicyIds) {
      return;
    }

    this.contractDefinitionService.queryAllContractDefinitions().subscribe({
      next: (definitions) => {
        const matching = (definitions || []).find((definition: any) =>
          this.contractDefinitionMatchesAsset(definition, this.data!.assetId)
        );
        if (!matching) {
          return;
        }

        const accessPolicyId = matching?.accessPolicyId || matching?.['edc:accessPolicyId'] || '';
        const contractPolicyId = matching?.contractPolicyId || matching?.['edc:contractPolicyId'] || '';

        this.data!.contractOffers = (this.data!.contractOffers || []).map((offer) => ({
          ...offer,
          accessPolicyId: offer.accessPolicyId || accessPolicyId,
          contractPolicyId: offer.contractPolicyId || contractPolicyId,
          policyIdsResolved: !!((offer.accessPolicyId || accessPolicyId) && (offer.contractPolicyId || contractPolicyId))
        }));
      },
      error: () => {
        // Keep fallback "Not exposed in catalog offer"
      }
    });
  }

  private syncAgreementStatus(): void {
    if (!this.data) {
      return;
    }
    this.contractNegotiationService.getAgreedAssetIds().subscribe({
      next: (agreedIds) => {
        const hasAgreement = agreedIds.has(this.data!.assetId);
        this.data!.contractOffers = (this.data!.contractOffers || []).map((offer) => ({
          ...offer,
          hasAgreement,
          negotiationInProgress: false
        }));
      },
      error: () => {
        // best effort only
      }
    });
  }

  private pollNegotiationStatus(negotiationId: string, offer: ContractOffer, remainingAttempts: number): void {
    this.contractNegotiationService.get(negotiationId).subscribe({
      next: (negotiation) => {
        const state = this.extractNegotiationState(negotiation);
        if (state === 'FINALIZED') {
          offer.negotiationInProgress = false;
          offer.hasAgreement = true;
          this.notificationService.showInfo('Contract negotiation finalized.');
          this.syncAgreementStatus();
          return;
        }
        if (state === 'TERMINATED' || state === 'DECLINED' || state === 'ERROR') {
          offer.negotiationInProgress = false;
          this.notificationService.showError(`Contract negotiation failed (${state}).`);
          return;
        }
        if (remainingAttempts <= 1) {
          offer.negotiationInProgress = false;
          this.notificationService.showWarning('Negotiation is pending. Please refresh in a few seconds.');
          this.syncAgreementStatus();
          return;
        }
        setTimeout(() => this.pollNegotiationStatus(negotiationId, offer, remainingAttempts - 1), this.negotiationPollDelayMs);
      },
      error: () => {
        offer.negotiationInProgress = false;
        this.notificationService.showWarning('Negotiation created, but status polling failed.');
      }
    });
  }

  private extractNegotiationState(negotiation: any): string {
    const candidates = [
      negotiation?.state,
      negotiation?.['edc:state'],
      negotiation?.negotiationState,
      negotiation?.['edc:negotiationState'],
      negotiation?.['https://w3id.org/edc/v0.0.1/ns/state']
    ];
    for (const value of candidates) {
      if (typeof value === 'string' && value.trim().length > 0) {
        return value.trim().toUpperCase();
      }
    }
    return 'UNKNOWN';
  }

  private extractAssigner(): string {
    const owner = this.data?.properties?.owner;
    if (typeof owner === 'string' && owner.trim().length > 0) {
      return owner.trim();
    }
    return this.connectorContextService.getCurrentRole() === 'provider' ? 'consumer' : 'provider';
  }

  private escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  private contractDefinitionMatchesAsset(definition: any, assetId: string): boolean {
    const selectorRaw = definition?.assetsSelector || definition?.['edc:assetsSelector'];
    if (!selectorRaw) {
      return false;
    }

    const selectors = Array.isArray(selectorRaw) ? selectorRaw : [selectorRaw];
    return selectors.some((selector: any) => {
      const operandLeft = selector?.operandLeft || selector?.['edc:operandLeft'] || '';
      const operator = selector?.operator || selector?.['edc:operator'] || '';
      const operandRightRaw = selector?.operandRight ?? selector?.['edc:operandRight'];
      const operandRight = Array.isArray(operandRightRaw) ? operandRightRaw : [operandRightRaw];
      const hasAssetId = operandRight.some((value: any) => {
        if (typeof value === 'string') {
          return value === assetId;
        }
        if (value && typeof value === 'object') {
          return value['@value'] === assetId || value['@id'] === assetId || value['id'] === assetId;
        }
        return false;
      });

      return operandLeft === 'https://w3id.org/edc/v0.0.1/ns/id' && operator.toLowerCase() === 'in' && hasAssetId;
    });
  }
}
