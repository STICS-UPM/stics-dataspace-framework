import { Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatChipsModule } from '@angular/material/chips';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatListModule } from '@angular/material/list';

import { MlBrowserService } from '../../shared/services/ml-browser.service';
import { NotificationService } from '../../shared/services/notification.service';
import { CatalogStateService } from '../../shared/services/catalog-state.service';

interface CatalogItem {
  '@id': string;
  '@type': string;
  assetId: string;
  properties: any;
  originator: string;
  contractOffers: ContractOffer[];
  contractCount: number;
}

interface ContractOffer {
  '@id': string;
  '@type': string;
  contractId: string;
  accessPolicyId: string;
  contractPolicyId: string;
  accessPolicy: any;
  contractPolicy: any;
}

/**
 * Catalog Component
 * 
 * Displays assets that have contract offers available
 * Similar to dataspace-connector-interface catalog browser
 */
@Component({
  selector: 'app-catalog',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatChipsModule,
    MatPaginatorModule,
    MatListModule
  ],
  template: `
    <div class="catalog-container">
      <div class="catalog-header">
        <h1>
          <mat-icon>store</mat-icon>
          Catalog Browser
        </h1>
        <p>Browse available datasets with contract offers</p>
      </div>

      <div class="section-header">
        <mat-paginator 
          (page)="changePage($event)" 
          [pageSize]="pageSize" 
          [length]="paginatorLength"
          [pageIndex]="currentPage" 
          [pageSizeOptions]="[5, 10, 20]">
        </mat-paginator>
      </div>

      @if (loading) {
        <div class="loading-spinner">
          <mat-spinner></mat-spinner>
          <p>Loading catalog...</p>
        </div>
      } @else if (catalogItems.length > 0) {
        <div class="catalog-grid">
          @for (item of catalogItems; track item.assetId) {
            <mat-card class="catalog-card">
              <mat-card-header>
                <mat-icon mat-card-avatar>sim_card</mat-icon>
                <mat-card-title>{{ item.properties?.name || item.assetId }}</mat-card-title>
                <mat-card-subtitle>
                  <mat-chip-set>
                    <mat-chip>{{ item.properties?.type || 'ML Model' }}</mat-chip>
                    <mat-chip color="accent">{{ item.contractCount }} contract{{ item.contractCount !== 1 ? 's' : '' }}</mat-chip>
                  </mat-chip-set>
                </mat-card-subtitle>
              </mat-card-header>
              
              <mat-card-content>
                <p class="description">
                  {{ item.properties?.description || 'No description available' }}
                </p>
                
                <mat-list dense>
                  @if (item.properties?.type) {
                    <mat-list-item>
                      <mat-icon matListItemIcon>category</mat-icon>
                      <div class="asset-property-name" matListItemTitle>Type</div>
                      <div matListItemLine>{{ item.properties.type }}</div>
                    </mat-list-item>
                  }
                  @if (item.originator) {
                    <mat-list-item>
                      <mat-icon matListItemIcon>link</mat-icon>
                      <div class="asset-property-name" matListItemTitle>Originator</div>
                      <div matListItemLine>{{ item.originator }}</div>
                    </mat-list-item>
                  }
                  @if (item.properties?.framework) {
                    <mat-list-item>
                      <mat-icon matListItemIcon>code</mat-icon>
                      <div class="asset-property-name" matListItemTitle>Framework</div>
                      <div matListItemLine>{{ item.properties.framework }}</div>
                    </mat-list-item>
                  }
                </mat-list>
              </mat-card-content>

              <mat-card-actions class="card-actions">
                <button mat-stroked-button color="accent" (click)="viewContractOffers(item)">
                  <mat-icon>visibility</mat-icon>
                  View details and contract offers
                </button>
              </mat-card-actions>
            </mat-card>
          }
        </div>
      } @else {
        <mat-card class="empty-state">
          <mat-card-content>
            <mat-icon>search_off</mat-icon>
            <h3>No offerings in catalog</h3>
            <p>There are no datasets with contract offers available at this moment.</p>
            <p class="hint">Create contract definitions for your assets to make them available in the catalog.</p>
          </mat-card-content>
        </mat-card>
      }
    </div>
  `,
  styles: [`
    .catalog-container {
      height: 100%;
      width: 100%;
      max-height: 100vh;
      max-width: 100vw;
      padding: 20px;
      box-sizing: border-box;
      overflow-y: auto;
      overflow-x: hidden;
      position: relative;
    }

    .catalog-header {
      margin-bottom: 24px;

      h1 {
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 2rem;
        color: #333;
        margin-bottom: 8px;

        mat-icon {
          font-size: 2rem;
          width: 2rem;
          height: 2rem;
          color: #667eea;
        }
      }

      p {
        color: #666;
        font-size: 1.1rem;
        margin-left: 44px;
      }
    }

    .section-header {
      display: flex;
      justify-content: flex-end;
      margin-bottom: 20px;
    }

    .loading-spinner {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 400px;
      gap: 16px;
    }

    .catalog-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
      gap: 24px;
    }

    .catalog-card {
      height: 100%;
      display: flex;
      flex-direction: column;
      transition: transform 0.2s, box-shadow 0.2s;

      &:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 16px rgba(0,0,0,0.1);
      }

      mat-card-header {
        margin-bottom: 16px;

        mat-icon[mat-card-avatar] {
          background-color: #667eea;
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
        }
      }

      mat-card-content {
        flex: 1;
      }

      .description {
        color: #666;
        margin-bottom: 16px;
        min-height: 40px;
        font-size: 0.95rem;
      }

      .asset-property-name {
        font-weight: 500;
        color: #333;
      }

      mat-list {
        padding-top: 8px;
      }

      mat-list-item {
        height: auto !important;
        min-height: 48px;
      }

      .card-actions {
        display: flex;
        justify-content: center;
        padding: 16px;

        button {
          width: 100%;
        }
      }
    }

    .empty-state {
      text-align: center;
      margin-top: 48px;
      padding: 48px;

      mat-icon {
        font-size: 72px;
        width: 72px;
        height: 72px;
        color: #ccc;
        margin-bottom: 16px;
      }

      h3 {
        color: #666;
        margin-bottom: 8px;
      }

      p {
        color: #999;
        margin: 8px 0;
      }

      .hint {
        color: #667eea;
        font-style: italic;
      }
    }
  `]
})
export class CatalogComponent implements OnInit {
  private mlBrowserService = inject(MlBrowserService);
  private notificationService = inject(NotificationService);
  private router = inject(Router);
  private catalogStateService = inject(CatalogStateService);

  catalogItems: CatalogItem[] = [];
  loading = false;

  // Pagination
  pageSize = 10;
  currentPage = 0;
  paginatorLength = 0;

  ngOnInit(): void {
    this.countCatalogItems();
    this.loadCatalog(this.currentPage);
  }

  changePage(event: PageEvent): void {
    const offset = event.pageIndex * event.pageSize;
    this.pageSize = event.pageSize;
    this.currentPage = event.pageIndex;
    this.loadCatalog(offset);
  }

  loadCatalog(offset: number): void {
    this.loading = true;

    const querySpec = {
      offset: offset,
      limit: this.pageSize
    };

    console.log('[Catalog] Loading catalog with offset:', offset, 'limit:', this.pageSize);

    this.mlBrowserService.getCatalog(querySpec).subscribe({
      next: (results) => {
        this.catalogItems = results;
        this.loading = false;
        console.log('[Catalog] Loaded', results.length, 'catalog items');
      },
      error: (error) => {
        console.error('[Catalog] Error loading catalog:', error);
        this.notificationService.showError('Failed to load catalog');
        this.loading = false;
      }
    });
  }

  countCatalogItems(): void {
    this.mlBrowserService.getCatalogCount().subscribe({
      next: (count) => {
        this.paginatorLength = count;
        console.log('[Catalog] Total items:', count);
      },
      error: (error) => {
        console.error('[Catalog] Error counting catalog items:', error);
      }
    });
  }

  viewContractOffers(item: CatalogItem): void {
    console.log('[Catalog] viewContractOffers called');
    console.log('[Catalog] Item:', item);
    
    // Store data in service
    this.catalogStateService.setCurrentItem({
      assetId: item.assetId,
      properties: item.properties,
      originator: item.originator,
      contractOffers: item.contractOffers,
      contractCount: item.contractCount,
      catalogView: true,
      returnUrl: '/catalog'
    });
    
    // Navigate to catalog detail view
    console.log('[Catalog] Navigating to /catalog/view');
    this.router.navigate(['/catalog/view']).then(
      (success) => console.log('[Catalog] Navigation success:', success),
      (error) => console.error('[Catalog] Navigation error:', error)
    );
  }
}
