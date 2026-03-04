import { Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { AssetService } from '../../shared/services/asset.service';
import { NotificationService } from '../../shared/services/notification.service';

/**
 * Asset Detail Component
 * 
 * Displays detailed information about a specific ML asset
 */
@Component({
  selector: 'app-asset-detail',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatProgressSpinnerModule
  ],
  template: `
    <div class="asset-detail-container">
      @if (loading) {
        <div class="loading-spinner">
          <mat-spinner></mat-spinner>
        </div>
      } @else if (asset) {
        <mat-card>
          <mat-card-header>
            <mat-card-title>
              <div class="title-row">
                <h2>{{ asset['edc:properties']?.['asset:prop:name'] || asset['@id'] }}</h2>
                <div class="badges">
                  @if (asset['edc:isLocal']) {
                    <span class="badge badge-local">LOCAL</span>
                  } @else {
                    <span class="badge badge-external">EXTERNAL</span>
                  }
                  @if (asset['edc:owner']) {
                    <span class="badge badge-owner">{{ asset['edc:owner'] }}</span>
                  }
                </div>
              </div>
            </mat-card-title>
          </mat-card-header>

          <mat-card-content>
            <!-- Asset ID -->
            <div class="detail-section">
              <div class="info-item">
                <strong>ID:</strong>
                <span>{{ asset['@id'] }}</span>
              </div>
            </div>

            <!-- Basic Information -->
            <div class="detail-section">
              <h3>Basic Information</h3>
              <div class="info-grid">
                <div class="info-item">
                  <strong>Name:</strong>
                  <span>{{ asset['edc:properties']?.['asset:prop:name'] || 'N/A' }}</span>
                </div>
                <div class="info-item">
                  <strong>Version:</strong>
                  <span>{{ asset['edc:properties']?.['asset:prop:version'] || 'N/A' }}</span>
                </div>
                <div class="info-item">
                  <strong>Format:</strong>
                  <span>{{ asset['edc:properties']?.['asset:prop:format'] || 'N/A' }}</span>
                </div>
                <div class="info-item">
                  <strong>Size:</strong>
                  <span>{{ formatBytes(asset['edc:properties']?.['asset:prop:byteSize']) }}</span>
                </div>
              </div>
            </div>

            <!-- Description -->
            <div class="detail-section">
              <h3>Description</h3>
              <p>{{ asset['edc:properties']?.['asset:prop:description'] || asset['edc:properties']?.['asset:prop:shortDescription'] || 'No description available' }}</p>
            </div>

            <!-- Keywords -->
            @if (asset['edc:properties']?.['asset:prop:keywords'] && getKeywords().length > 0) {
              <div class="detail-section">
                <h3>Keywords</h3>
                <mat-chip-set>
                  @for (keyword of getKeywords(); track keyword) {
                    <mat-chip>{{ keyword }}</mat-chip>
                  }
                </mat-chip-set>
              </div>
            }

            <!-- ML Ontology Metadata -->
            <div class="detail-section">
              <h3>ML Ontology Metadata</h3>
              <div class="info-grid">
                <div class="info-item">
                  <strong>Task:</strong>
                  <span>{{ asset['edc:properties']?.['ml:metadata']?.task || 'N/A' }}</span>
                </div>
                <div class="info-item">
                  <strong>Subtask:</strong>
                  <span>{{ asset['edc:properties']?.['ml:metadata']?.subtask || 'N/A' }}</span>
                </div>
                <div class="info-item">
                  <strong>Algorithm:</strong>
                  <span>{{ asset['edc:properties']?.['ml:metadata']?.algorithm || 'N/A' }}</span>
                </div>
                <div class="info-item">
                  <strong>Software:</strong>
                  <span>{{ asset['edc:properties']?.['ml:metadata']?.software || 'N/A' }}</span>
                </div>
              </div>
            </div>

            <!-- Storage Information -->
            <div class="detail-section">
              <h3>Storage Information</h3>
              <div class="info-grid">
                <div class="info-item">
                  <strong>Storage Type:</strong>
                  <span>{{ asset['edc:dataAddress']?.['@type'] || 'N/A' }}</span>
                </div>
                <div class="info-item">
                  <strong>Destination:</strong>
                  <span>{{ asset['edc:dataAddress']?.['bucketName'] || 'N/A' }}</span>
                </div>
                <div class="info-item full-width">
                  <strong>File Name:</strong>
                  <span>{{ asset['edc:dataAddress']?.['s3Key'] || 'N/A' }}</span>
                </div>
              </div>
            </div>
          </mat-card-content>

          <mat-card-actions>
            <button mat-raised-button (click)="goBack()">
              <mat-icon>arrow_back</mat-icon>
              Back to Assets
            </button>
            <button mat-raised-button color="primary" (click)="createOffer()">
              <mat-icon>add_circle</mat-icon>
              Create Offer
            </button>
          </mat-card-actions>
        </mat-card>
      } @else {
        <mat-card>
          <mat-card-content>
            <p>Asset not found</p>
          </mat-card-content>
          <mat-card-actions>
            <button mat-raised-button (click)="goBack()">
              <mat-icon>arrow_back</mat-icon>
              Back to Assets
            </button>
          </mat-card-actions>
        </mat-card>
      }
    </div>
  `,
  styles: [`
    .asset-detail-container {
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

    .loading-spinner {
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 400px;
    }

    mat-card {
      margin-bottom: 24px;
    }

    .title-row {
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }

    .badges {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .badge {
      padding: 4px 12px;
      border-radius: 12px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      border: 1px solid;
    }

    .badge-local {
      background-color: #e8f5e9;
      color: #2e7d32;
      border-color: #c8e6c9;
    }

    .badge-external {
      background-color: #fff3e0;
      color: #e65100;
      border-color: #ffe0b2;
    }

    .badge-owner {
      background-color: #e3f2fd;
      color: #1976d2;
      border-color: #bbdefb;
    }

    .detail-section {
      margin-bottom: 24px;

      h3 {
        color: #667eea;
        margin-bottom: 12px;
        font-size: 1.2rem;
      }
    }

    .info-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 16px;
    }

    .full-width {
      grid-column: 1 / -1;
    }

    .info-item {
      display: flex;
      flex-direction: column;
      gap: 4px;

      strong {
        color: #666;
        font-size: 0.9rem;
      }

      span {
        font-size: 1rem;
      }
    }

    mat-chip-set {
      margin-top: 8px;
    }

    mat-card-actions {
      display: flex;
      gap: 12px;
      padding: 16px;
    }
  `]
})
export class AssetDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private assetService = inject(AssetService);
  private notificationService = inject(NotificationService);

  asset: any = null;
  loading = true;

  ngOnInit(): void {
    const routeId = this.route.snapshot.paramMap.get('id');
    const assetId = routeId ? this.safeDecodeURIComponent(routeId) : null;
    console.log('[Asset Detail] ngOnInit - Asset ID from route:', assetId);
    if (assetId) {
      this.loadAsset(assetId);
    } else {
      console.error('[Asset Detail] No asset ID found in route');
      this.loading = false;
    }
  }

  loadAsset(id: string): void {
    console.log('[Asset Detail] Loading asset:', id);
    this.loading = true;
    this.assetService.getAsset(id).subscribe({
      next: (asset) => {
        console.log('[Asset Detail] Asset loaded successfully:', asset);
        this.asset = asset;
        this.loading = false;
      },
      error: (error) => {
        console.error('[Asset Detail] Error loading asset:', error);
        this.notificationService.showError('Error loading asset details');
        this.loading = false;
      }
    });
  }

  getKeywords(): string[] {
    const keywords = this.asset?.['edc:properties']?.['asset:prop:keywords'];
    if (typeof keywords === 'string') {
      return keywords.split(',').map((k: string) => k.trim()).filter((k: string) => k);
    }
    if (Array.isArray(keywords)) {
      return keywords;
    }
    return [];
  }

  formatBytes(bytes: string | number | undefined): string {
    if (!bytes) return 'N/A';
    const numBytes = typeof bytes === 'string' ? parseInt(bytes, 10) : bytes;
    if (isNaN(numBytes) || numBytes === 0) return 'N/A';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(numBytes) / Math.log(k));
    
    return `${(numBytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
  }

  formatDate(dateString: string | undefined): string {
    if (!dateString) return 'N/A';
    try {
      const date = new Date(dateString);
      return date.toLocaleString();
    } catch {
      return dateString;
    }
  }

  goBack(): void {
    this.router.navigate(['/ml-assets']);
  }

  createOffer(): void {
    this.notificationService.showInfo('Contract offer creation will be implemented in next phase');
  }

  private safeDecodeURIComponent(value: string): string {
    try {
      return decodeURIComponent(value);
    } catch {
      return value;
    }
  }
}
