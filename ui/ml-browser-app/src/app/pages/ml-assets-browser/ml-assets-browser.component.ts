import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { finalize } from 'rxjs/operators';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';

import { MlAssetsService, MLAssetFilter } from '../../shared/services/ml-assets.service';
import { MLAsset } from '../../shared/models/ml-asset';
import { NotificationService } from '../../shared/services/notification.service';
import { MlAssetCardComponent } from './components/ml-asset-card/ml-asset-card.component';
import { MlFiltersComponent } from './components/ml-filters/ml-filters.component';
import { MlSearchBarComponent } from '../../components/ml-search-bar/ml-search-bar.component';
import { MlBrowserService } from '../../shared/services/ml-browser.service';
import { CatalogStateService } from '../../shared/services/catalog-state.service';
import { ContractNegotiationService } from '../../shared/services/contract-negotiation.service';
import { ConnectorContextService } from '../../shared/services/connector-context.service';
import { environment } from '../../../environments/environment';

@Component({
  selector: 'app-ml-assets-browser',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatProgressSpinnerModule,
    MatIconModule,
    MatButtonModule,
    MatPaginatorModule,
    MlAssetCardComponent,
    MlFiltersComponent,
    MlSearchBarComponent
  ],
  templateUrl: './ml-assets-browser.component.html',
  styleUrl: './ml-assets-browser.component.scss'
})
export class MlAssetsBrowserComponent implements OnInit {
  private readonly mlAssetsService = inject(MlAssetsService);
  private readonly notificationService = inject(NotificationService);
  private readonly router = inject(Router);
  private readonly mlBrowserService = inject(MlBrowserService);
  private readonly catalogStateService = inject(CatalogStateService);
  private readonly contractNegotiationService = inject(ContractNegotiationService);
  private readonly connectorContextService = inject(ConnectorContextService);

  allAssets: MLAsset[] = [];
  filteredAssets: MLAsset[] = [];
  displayedAssets: MLAsset[] = [];

  availableTasks: string[] = [];
  availableSubtasks: string[] = [];
  availableAlgorithms: string[] = [];
  availableLibraries: string[] = [];
  availableFrameworks: string[] = [];
  availableStorageTypes: string[] = [];
  availableSoftware: string[] = [];
  availableAssetSources: string[] = [];
  availableFormats: string[] = [];

  isLoading = false;
  isError = false;
  errorMessage = '';

  // Search and filters
  currentSearch = '';
  currentFilters: MLAssetFilter = {};

  // Pagination
  pageSize = 12;
  currentPage = 0;
  totalItems = 0;

  gridCols = 3;
  private readonly negotiationPollDelayMs = 2000;
  private readonly negotiationPollMaxAttempts = 30;

  ngOnInit(): void {
    this.loadMachinelearningAssets();
    this.adjustGridCols();
    window.addEventListener('resize', () => this.adjustGridCols());
  }

  loadMachinelearningAssets(): void {
    console.log('[ML Browser Component] Starting to load IA assets...');
    this.isLoading = true;
    this.isError = false;

    this.fetchAssetsFromServer();
  }

  /**
   * Updates available filters based on all loaded assets
   */
  private updateAvailableFilters(): void {
    this.availableTasks = this.mlAssetsService.extractUniqueTasks(this.allAssets);
    this.availableSubtasks = this.mlAssetsService.extractUniqueSubtasks(this.allAssets);
    this.availableAlgorithms = this.mlAssetsService.extractUniqueAlgorithms(this.allAssets);
    this.availableLibraries = this.mlAssetsService.extractUniqueLibraries(this.allAssets);
    this.availableFrameworks = this.mlAssetsService.extractUniqueFrameworks(this.allAssets);
    this.availableStorageTypes = this.mlAssetsService.extractUniqueStorageTypes(this.allAssets);
    this.availableSoftware = this.mlAssetsService.extractUniqueSoftware(this.allAssets);
    this.availableAssetSources = this.mlAssetsService.extractUniqueAssetSources(this.allAssets);
    this.availableFormats = this.mlAssetsService.extractUniqueFormats(this.allAssets);
  }

  onSearch(searchTerm: string): void {
    this.currentSearch = searchTerm;
    this.currentPage = 0;
    this.fetchAssetsFromServer();
  }

  onFilterChange(filters: MLAssetFilter): void {
    this.currentFilters = filters;
    this.currentPage = 0;
    this.fetchAssetsFromServer();
  }

  private fetchAssetsFromServer(): void {
    const hasFilters = this.hasActiveFilters();
    const combinedFilters: MLAssetFilter = {
      searchTerm: this.currentSearch,
      ...this.currentFilters
    };

    this.isLoading = true;
    this.isError = false;

    this.mlAssetsService.getMachinelearningAssets(this.currentFilters, this.currentSearch)
      .pipe(finalize(() => {
        this.isLoading = false;
      }))
      .subscribe({
        next: (assets: MLAsset[]) => {
          console.log('[ML Browser Component] Received assets:', assets.length);
          this.filteredAssets = assets;
          if (!hasFilters || this.allAssets.length === 0) {
            this.allAssets = assets;
            this.updateAvailableFilters();
          }
          this.syncAgreementStatus();
          this.totalItems = this.filteredAssets.length;
          this.updateDisplayedAssets();
          this.notificationService.showInfo(`Loaded ${this.allAssets.length} IA models`);
        },
        error: (error: unknown) => {
          console.error('[ML Browser Component] Error loading assets:', error);
          this.isError = true;
          const errorObj = error as Record<string, unknown>;
          this.errorMessage = 'Failed to load ML models: ' + (errorObj?.['message'] || 'Unknown error');
          this.notificationService.showError(this.errorMessage);
        }
      });
  }

  private updateDisplayedAssets(): void {
    const startIdx = this.currentPage * this.pageSize;
    const endIdx = startIdx + this.pageSize;
    this.displayedAssets = this.filteredAssets.slice(startIdx, endIdx);
  }

  private hasActiveFilters(): boolean {
    if (this.currentSearch && this.currentSearch.trim().length > 0) {
      return true;
    }
    const filters = this.currentFilters || {};
    return !!(
      (filters.tasks && filters.tasks.length > 0) ||
      (filters.subtasks && filters.subtasks.length > 0) ||
      (filters.algorithms && filters.algorithms.length > 0) ||
      (filters.libraries && filters.libraries.length > 0) ||
      (filters.frameworks && filters.frameworks.length > 0) ||
      (filters.storageTypes && filters.storageTypes.length > 0) ||
      (filters.software && filters.software.length > 0) ||
      (filters.assetSources && filters.assetSources.length > 0) ||
      (filters.formats && filters.formats.length > 0)
    );
  }

  onPageChange(event: PageEvent): void {
    this.currentPage = event.pageIndex;
    this.pageSize = event.pageSize;
    this.updateDisplayedAssets();
  }

  onViewDetails(asset: MLAsset): void {
    console.log('[ML Browser] View details for asset:', asset.id);
    const offers = Array.isArray(asset.contractOffers) ? asset.contractOffers as any[] : [];
    this.catalogStateService.setCurrentItem({
      assetId: asset.id,
      properties: this.toCatalogDetailProperties(asset),
      originator: asset.originator || (asset.isLocal ? 'Local Connector' : 'Federated Catalog'),
      contractOffers: offers,
      contractCount: offers.length,
      catalogView: true,
      returnUrl: '/ml-assets',
      selectedTabIndex: 0
    });
    this.router.navigate(['/catalog/view']);
  }

  onDownloadAsset(asset: MLAsset): void {
    this.notificationService.showInfo(`Preparing to access "${asset.name}"...`);
    // TODO: Implement download/access logic
  }

  onCreateContract(asset: MLAsset): void {
    console.log('[ML Browser] Create contract for asset:', asset.name, asset.id);
    // Navigate to contract definition creation with pre-selected asset
    this.router.navigate(['/contract-definitions/create'], {
      state: { preSelectedAssetId: asset.id }
    });
  }

  onNegotiate(asset: MLAsset): void {
    console.log('[ML Browser] Negotiate for asset:', asset.name);
    if (asset.hasAgreement) {
      this.notificationService.showInfo(`"${asset.name}" already has a contract agreement`);
      return;
    }
    if (asset.negotiationInProgress) {
      this.notificationService.showInfo(`Negotiation already in progress for "${asset.name}"`);
      return;
    }
    this.notificationService.showInfo(`Starting negotiation for "${asset.name}"`);

    const offerId = this.resolveOfferId(asset);
    if (offerId) {
      this.startNegotiation(asset, offerId);
      return;
    }

    this.mlBrowserService.getCatalog({ offset: 0, limit: 100 }).subscribe({
      next: (catalogItems) => {
        const catalogItem = catalogItems.find(item => item.assetId === asset.id);
        const catalogOfferId = this.resolveOfferIdFromCatalog(catalogItem);

        if (catalogOfferId) {
          this.startNegotiation(asset, catalogOfferId);
          return;
        }

        if (catalogItem && catalogItem.contractOffers && catalogItem.contractOffers.length > 0) {
          this.catalogStateService.setCurrentItem({
            assetId: catalogItem.assetId,
            properties: catalogItem.properties,
            originator: catalogItem.originator,
            contractOffers: catalogItem.contractOffers,
            contractCount: catalogItem.contractCount,
            catalogView: true,
            returnUrl: '/ml-assets',
            selectedTabIndex: 1
          });
          this.router.navigate(['/catalog/view']);
          return;
        }

        console.warn('[ML Browser] No contract offers found for asset:', asset.id);
        this.notificationService.showWarning(`No contract offers available for "${asset.name}"`);
      },
      error: (error) => {
        console.error('[ML Browser] Error fetching catalog:', error);
        this.notificationService.showError('Failed to load contract offers');
      }
    });
  }

  private startNegotiation(asset: MLAsset, offerId: string): void {
    this.setAssetNegotiationInProgress(asset.id, true);
    const counterPartyParticipantId = this.connectorContextService.getCurrentRole() === 'provider' ? 'consumer' : 'provider';
    const request = {
      '@type': 'ContractRequest',
      counterPartyAddress: this.connectorContextService.getCounterPartyProtocolUrl(),
      protocol: environment.runtime.catalogProtocol,
      policy: {
        '@context': 'http://www.w3.org/ns/odrl.jsonld',
        '@id': offerId,
        '@type': 'Offer',
        assigner: asset.participantId || counterPartyParticipantId,
        target: asset.id
      }
    };

    this.contractNegotiationService.initiate(request).subscribe({
      next: (result) => {
        const negotiationId = result?.['@id'] || result?.id || 'created';
        this.notificationService.showInfo(`Contract negotiation started: ${negotiationId}`);
        if (typeof negotiationId === 'string' && negotiationId !== 'created') {
          this.pollNegotiationStatus(negotiationId, asset.id, this.negotiationPollMaxAttempts);
        } else {
          this.setAssetNegotiationInProgress(asset.id, false);
          this.syncAgreementStatus();
        }
      },
      error: (error) => {
        this.setAssetNegotiationInProgress(asset.id, false);
        console.error('[ML Browser] Error creating contract negotiation:', error);
        const msg = error?.error?.message || error?.message || 'Unknown error';
        this.notificationService.showError(`Failed to negotiate contract: ${msg}`);
      }
    });
  }

  private resolveOfferId(asset: MLAsset): string | null {
    const offers = Array.isArray(asset.contractOffers) ? asset.contractOffers : [];
    if (offers.length === 0) {
      return null;
    }

    const firstOffer = offers[0] as Record<string, unknown>;
    return (
      (typeof firstOffer['@id'] === 'string' && firstOffer['@id']) ||
      (typeof firstOffer['contractId'] === 'string' && firstOffer['contractId']) ||
      null
    );
  }

  private resolveOfferIdFromCatalog(catalogItem: any): string | null {
    if (!catalogItem || !Array.isArray(catalogItem.contractOffers) || catalogItem.contractOffers.length === 0) {
      return null;
    }

    const firstOffer = catalogItem.contractOffers[0] as Record<string, unknown>;
    return (
      (typeof firstOffer['@id'] === 'string' && firstOffer['@id']) ||
      (typeof firstOffer['contractId'] === 'string' && firstOffer['contractId']) ||
      null
    );
  }

  private pollNegotiationStatus(negotiationId: string, assetId: string, remainingAttempts: number): void {
    this.contractNegotiationService.get(negotiationId).subscribe({
      next: (negotiation) => {
        const state = this.extractNegotiationState(negotiation);
        if (state === 'FINALIZED') {
          this.setAssetNegotiationInProgress(assetId, false);
          this.markAssetHasAgreement(assetId, true);
          this.notificationService.showInfo(`Contract negotiation finalized for asset ${assetId}`);
          return;
        }

        if (state === 'TERMINATED' || state === 'DECLINED' || state === 'ERROR') {
          this.setAssetNegotiationInProgress(assetId, false);
          this.notificationService.showError(`Contract negotiation failed (${state}) for asset ${assetId}`);
          return;
        }

        if (remainingAttempts <= 1) {
          this.setAssetNegotiationInProgress(assetId, false);
          this.notificationService.showWarning('Negotiation started. Still pending, please refresh in a few seconds.');
          this.syncAgreementStatus();
          return;
        }

        setTimeout(() => this.pollNegotiationStatus(negotiationId, assetId, remainingAttempts - 1), this.negotiationPollDelayMs);
      },
      error: (error) => {
        console.error('[ML Browser] Error polling negotiation status:', error);
        this.setAssetNegotiationInProgress(assetId, false);
        this.notificationService.showWarning('Negotiation created, but status polling failed. Please refresh.');
        this.syncAgreementStatus();
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

  private syncAgreementStatus(): void {
    this.contractNegotiationService.getAgreedAssetIds().subscribe({
      next: (agreedIds) => {
        this.applyAgreementFlags(this.allAssets, agreedIds);
        this.applyAgreementFlags(this.filteredAssets, agreedIds);
        this.updateDisplayedAssets();
      },
      error: (error) => {
        console.warn('[ML Browser] Failed to load agreement status for assets:', error);
      }
    });
  }

  private applyAgreementFlags(assets: MLAsset[], agreedIds: Set<string>): void {
    assets.forEach((asset) => {
      if (asset.isLocal) {
        asset.hasAgreement = true;
      } else {
        asset.hasAgreement = agreedIds.has(asset.id);
      }
      if (!asset.negotiationInProgress) {
        asset.negotiationInProgress = false;
      }
    });
  }

  private setAssetNegotiationInProgress(assetId: string, inProgress: boolean): void {
    const update = (assets: MLAsset[]) => {
      assets.forEach((asset) => {
        if (asset.id === assetId && !asset.isLocal) {
          asset.negotiationInProgress = inProgress;
        }
      });
    };
    update(this.allAssets);
    update(this.filteredAssets);
    this.updateDisplayedAssets();
  }

  private markAssetHasAgreement(assetId: string, hasAgreement: boolean): void {
    const update = (assets: MLAsset[]) => {
      assets.forEach((asset) => {
        if (asset.id === assetId && !asset.isLocal) {
          asset.hasAgreement = hasAgreement;
          asset.negotiationInProgress = false;
        }
      });
    };
    update(this.allAssets);
    update(this.filteredAssets);
    this.updateDisplayedAssets();
  }

  private toCatalogDetailProperties(asset: MLAsset): Record<string, unknown> {
    const source = (asset.rawProperties || asset.assetData || {}) as Record<string, unknown>;
    const read = (...keys: string[]): string => {
      for (const key of keys) {
        const value = source[key];
        if (typeof value === 'string' && value.trim().length > 0) {
          return value;
        }
      }
      return '';
    };

    return {
      ...source,
      id: asset.id,
      name: asset.name || read('name', 'asset:prop:name'),
      version: asset.version || read('version', 'asset:prop:version'),
      contentType: asset.contentType || read('contenttype', 'asset:prop:contenttype'),
      description: asset.description || read('description', 'asset:prop:description'),
      shortDescription: asset.shortDescription || read('shortDescription', 'asset:prop:shortDescription'),
      keywords: asset.keywords,
      byteSize: asset.byteSize || read('byteSize', 'asset:prop:byteSize'),
      format: asset.format || read('format', 'asset:prop:format'),
      type: asset.assetType || read('type', 'asset:prop:type'),
      owner: asset.owner || asset.participantId || ''
    };
  }

  retryLoading(): void {
    this.loadMachinelearningAssets();
  }

  private adjustGridCols(): void {
    const width = window.innerWidth;
    if (width > 1600) {
      this.gridCols = 4;
    } else if (width > 1200) {
      this.gridCols = 3;
    } else if (width > 768) {
      this.gridCols = 2;
    } else {
      this.gridCols = 1;
    }
  }

  get hasResults(): boolean {
    return this.filteredAssets.length > 0;
  }

  get noResultsMessage(): string {
    if (this.allAssets.length === 0) {
      return 'No ML models found in the dataspace';
    }
    if (this.currentSearch || Object.keys(this.currentFilters).length > 0) {
      return 'No ML models match your search or filters';
    }
    return 'No results';
  }
}
