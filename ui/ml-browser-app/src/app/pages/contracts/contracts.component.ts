import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ContractDefinitionService } from '../../shared/services/contract-definition.service';
import { NotificationService } from '../../shared/services/notification.service';

/**
 * Contracts Component
 * 
 * Displays contract definitions created in the system
 */
@Component({
  selector: 'app-contracts',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatChipsModule,
    MatTooltipModule
  ],
  template: `
    <div class="contracts-container">
      <div class="contracts-header">
        <div class="header-content">
          <h1>
            <mat-icon>policy</mat-icon>
            Contract Definitions
          </h1>
          <p>Manage and view created contract definitions</p>
        </div>
        <div class="header-actions">
          <button mat-raised-button color="accent" (click)="createContract()">
            <mat-icon>add_circle_outline</mat-icon>
            Create Contract
          </button>
        </div>
      </div>

      @if (loading()) {
        <div class="loading-spinner">
          <mat-spinner></mat-spinner>
          <p>Loading contracts...</p>
        </div>
      } @else if (contracts().length > 0) {
        <div class="contracts-grid">
          @for (contract of contracts(); track contract['@id']) {
            <mat-card class="contract-card">
              <mat-card-header>
                <mat-icon mat-card-avatar class="contract-icon">policy</mat-icon>
                <mat-card-title>{{ contract['@id'] }}</mat-card-title>
                <mat-card-subtitle>Contract Definition</mat-card-subtitle>
              </mat-card-header>
              
              <mat-card-content>
                <div class="contract-details">
                  <!-- Access Policy Section -->
                  <div class="policy-section">
                    <div class="policy-header">
                      <mat-icon class="detail-icon">lock</mat-icon>
                      <span class="policy-title">Access Policy</span>
                    </div>
                    <div class="policy-content">
                      <div class="policy-id">
                        <span class="label">Policy ID:</span>
                        <span class="value">{{ contract.accessPolicyId || 'N/A' }}</span>
                      </div>
                      @if (contract.accessPolicy) {
                        <div class="policy-details">
                          <div class="policy-action">
                            <mat-icon>play_arrow</mat-icon>
                            <span>{{ getPolicyAction(contract.accessPolicy) }}</span>
                          </div>
                          @if (getPolicyConstraints(contract.accessPolicy).length > 0) {
                            <div class="constraints">
                              <span class="constraints-label">Constraints:</span>
                              <div class="constraint-list">
                                @for (constraint of getPolicyConstraints(contract.accessPolicy); track $index) {
                                  <div class="constraint-item">
                                    <mat-chip>
                                      {{ constraint.leftOperand }} {{ constraint.operator }} {{ constraint.rightOperand }}
                                    </mat-chip>
                                  </div>
                                }
                              </div>
                            </div>
                          }
                        </div>
                      }
                    </div>
                  </div>

                  <!-- Contract Policy Section -->
                  <div class="policy-section">
                    <div class="policy-header">
                      <mat-icon class="detail-icon">description</mat-icon>
                      <span class="policy-title">Contract Policy</span>
                    </div>
                    <div class="policy-content">
                      <div class="policy-id">
                        <span class="label">Policy ID:</span>
                        <span class="value">{{ contract.contractPolicyId || 'N/A' }}</span>
                      </div>
                      @if (contract.contractPolicy) {
                        <div class="policy-details">
                          <div class="policy-action">
                            <mat-icon>play_arrow</mat-icon>
                            <span>{{ getPolicyAction(contract.contractPolicy) }}</span>
                          </div>
                          @if (getPolicyConstraints(contract.contractPolicy).length > 0) {
                            <div class="constraints">
                              <span class="constraints-label">Constraints:</span>
                              <div class="constraint-list">
                                @for (constraint of getPolicyConstraints(contract.contractPolicy); track $index) {
                                  <div class="constraint-item">
                                    <mat-chip>
                                      {{ constraint.leftOperand }} {{ constraint.operator }} {{ constraint.rightOperand }}
                                    </mat-chip>
                                  </div>
                                }
                              </div>
                            </div>
                          }
                        </div>
                      }
                    </div>
                  </div>

                  <!-- Assets Section -->
                  <div class="assets-section">
                    <div class="assets-header">
                      <mat-icon>storage</mat-icon>
                      <span>Associated Assets</span>
                    </div>
                    <div class="assets-chips">
                      @if (contract.assetIds && contract.assetIds.length > 0) {
                        @for (assetId of contract.assetIds; track assetId) {
                          <mat-chip>{{ assetId }}</mat-chip>
                        }
                      } @else {
                        <span class="no-assets">No assets associated</span>
                      }
                    </div>
                  </div>

                  <!-- Metadata -->
                  <div class="metadata">
                    <span class="created-date">
                      <mat-icon>schedule</mat-icon>
                      Created: {{ formatDate(contract._metadata?.createdAt) }}
                    </span>
                  </div>
                </div>
              </mat-card-content>

              <mat-card-actions align="end">
                <button mat-button color="primary" (click)="viewDetails(contract)">
                  <mat-icon>visibility</mat-icon>
                  View Details
                </button>
                <button mat-button color="accent" (click)="viewAssets(contract)">
                  <mat-icon>storage</mat-icon>
                  View Assets
                </button>
              </mat-card-actions>
            </mat-card>
          }
        </div>
      } @else {
        <mat-card class="empty-state">
          <mat-card-content>
            <mat-icon>policy</mat-icon>
            <h3>No contract definitions found</h3>
            <p>You haven't created any contract definitions yet. Start by creating one for your IA assets.</p>
            <button mat-raised-button color="accent" (click)="createContract()">
              <mat-icon>add_circle_outline</mat-icon>
              Create Contract Definition
            </button>
          </mat-card-content>
        </mat-card>
      }
    </div>
  `,
  styles: [`
    .contracts-container {
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

    .contracts-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 30px;
      gap: 24px;

      @media (max-width: 768px) {
        flex-direction: column;
        align-items: stretch;
      }
    }

    .header-content {
      flex: 1;

      h1 {
        display: flex;
        align-items: center;
        gap: 12px;
        margin: 0 0 8px 0;
        font-size: 32px;
        font-weight: 500;

        mat-icon {
          font-size: 36px;
          width: 36px;
          height: 36px;
          color: #667eea;
        }
      }

      p {
        margin: 0;
        color: rgba(0, 0, 0, 0.6);
        font-size: 16px;
      }
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .loading-spinner {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 400px;
      gap: 16px;

      p {
        color: #666;
        font-size: 16px;
      }
    }

    .contracts-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
      gap: 24px;
      margin-bottom: 24px;

      @media (max-width: 768px) {
        grid-template-columns: 1fr;
      }
    }

    .contract-card {
      height: 100%;
      display: flex;
      flex-direction: column;
      transition: transform 0.2s, box-shadow 0.2s;

      &:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.1);
      }

      mat-card-header {
        .contract-icon {
          background-color: #667eea;
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        mat-card-title {
          font-size: 18px;
          font-weight: 500;
        }

        mat-card-subtitle {
          font-size: 14px;
          color: #666;
        }
      }

      mat-card-content {
        flex: 1;
        padding: 16px;
      }

      mat-card-actions {
        padding: 12px 16px;
        border-top: 1px solid #e0e0e0;
      }
    }

    .contract-details {
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    .policy-section {
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      padding: 12px;
      background-color: #f9f9f9;

      .policy-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid #e0e0e0;

        mat-icon {
          color: #667eea;
          font-size: 20px;
          width: 20px;
          height: 20px;
        }

        .policy-title {
          font-weight: 500;
          font-size: 14px;
          color: #333;
        }
      }

      .policy-content {
        display: flex;
        flex-direction: column;
        gap: 8px;

        .policy-id {
          display: flex;
          gap: 8px;
          font-size: 13px;

          .label {
            font-weight: 500;
            color: #666;
          }

          .value {
            color: #333;
            font-family: monospace;
          }
        }

        .policy-details {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-top: 4px;

          .policy-action {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 10px;
            background-color: #667eea;
            color: white;
            border-radius: 4px;
            font-size: 13px;
            font-weight: 500;
            width: fit-content;

            mat-icon {
              font-size: 16px;
              width: 16px;
              height: 16px;
            }
          }

          .constraints {
            display: flex;
            flex-direction: column;
            gap: 6px;

            .constraints-label {
              font-size: 12px;
              font-weight: 500;
              color: #666;
            }

            .constraint-list {
              display: flex;
              flex-direction: column;
              gap: 4px;

              .constraint-item {
                mat-chip {
                  font-size: 11px;
                  height: 24px;
                  background-color: #fff;
                  border: 1px solid #ddd;
                  font-family: monospace;
                }
              }
            }
          }
        }
      }
    }

    .assets-section {
      .assets-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
        font-size: 13px;
        font-weight: 500;
        color: #666;

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
          color: #667eea;
        }
      }
    }

    .assets-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;

      mat-chip {
        font-size: 12px;
        min-height: 28px;
      }

      .no-assets {
        font-size: 13px;
        color: #999;
        font-style: italic;
      }
    }

    .metadata {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #f0f0f0;

      .created-date {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        color: #666;

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
        }
      }
    }

    .empty-state {
      text-align: center;
      padding: 64px 24px;

      mat-icon {
        font-size: 64px;
        width: 64px;
        height: 64px;
        color: #ccc;
        margin-bottom: 16px;
      }

      h3 {
        color: #666;
        margin: 0 0 8px 0;
        font-size: 24px;
      }

      p {
        color: #999;
        margin: 0 0 24px 0;
        font-size: 16px;
      }
    }
  `]
})
export class ContractsComponent implements OnInit {
  private contractDefinitionService = inject(ContractDefinitionService);
  private notificationService = inject(NotificationService);
  private router = inject(Router);

  contracts = signal<any[]>([]);
  loading = signal(true);

  ngOnInit(): void {
    this.loadContracts();
  }

  loadContracts(): void {
    this.loading.set(true);
    this.contractDefinitionService.queryAllContractDefinitions().subscribe({
      next: (contracts: any[]) => {
        console.log('[Contracts] Raw response from service:', contracts);
        console.log('[Contracts] First contract:', contracts[0]);
        const normalizedContracts = (contracts || []).map((contract) => this.normalizeContract(contract));
        this.contracts.set(normalizedContracts);
        this.loading.set(false);
      },
      error: (error: any) => {
        console.error('[Contracts] Error loading contract definitions:', error);
        this.notificationService.showError('Error loading contract definitions');
        this.contracts.set([]);
        this.loading.set(false);
      }
    });
  }

  formatDate(dateValue: string | number | null | undefined): string {
    if (dateValue === null || dateValue === undefined || dateValue === '') return 'N/A';
    try {
      const date = typeof dateValue === 'number' ? new Date(dateValue) : new Date(String(dateValue));
      if (Number.isNaN(date.getTime())) {
        return 'N/A';
      }
      return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      });
    } catch {
      return 'N/A';
    }
  }

  getPolicyAction(policy: any): string {
    try {
      if (!policy) return 'N/A';
      
      // Handle nested policy structure (backend returns {policy: {odrl:permission: ...}})
      const policyData = policy.policy || policy;
      
      const permission = policyData['odrl:permission'];
      if (!permission || !Array.isArray(permission) || permission.length === 0) {
        return 'N/A';
      }
      const action = permission[0]['odrl:action'];
      return action || 'N/A';
    } catch (error) {
      console.error('Error extracting policy action:', error);
      return 'N/A';
    }
  }

  getPolicyConstraints(policy: any): any[] {
    try {
      if (!policy) return [];
      
      // Handle nested policy structure (backend returns {policy: {odrl:permission: ...}})
      const policyData = policy.policy || policy;
      
      const permission = policyData['odrl:permission'];
      if (!permission || !Array.isArray(permission) || permission.length === 0) {
        return [];
      }
      const constraints = permission[0]['odrl:constraint'];
      if (!constraints || !Array.isArray(constraints)) {
        return [];
      }
      return constraints.map(c => ({
        leftOperand: c['odrl:leftOperand'] || 'N/A',
        operator: c['odrl:operator'] || 'N/A',
        rightOperand: c['odrl:rightOperand'] || 'N/A'
      }));
    } catch (error) {
      console.error('Error extracting policy constraints:', error);
      return [];
    }
  }

  viewDetails(contract: any): void {
    this.notificationService.showInfo(`Contract: ${contract['@id']}`);
    // TODO: Navigate to contract details page
  }

  viewAssets(contract: any): void {
    if (contract.assetIds && contract.assetIds.length > 0) {
      const assetId = contract.assetIds[0];
      this.router.navigate(['/assets', assetId]);
    } else {
      this.notificationService.showInfo('No assets associated with this contract');
    }
  }

  createContract(): void {
    this.router.navigate(['/contract-definitions/create']);
  }

  private normalizeContract(contract: any): any {
    const accessPolicyId = contract.accessPolicyId || contract['edc:accessPolicyId'] || '';
    const contractPolicyId = contract.contractPolicyId || contract['edc:contractPolicyId'] || '';
    const assetIds = this.extractAssetIds(contract);
    const createdAt = this.extractCreatedAt(contract);

    return {
      ...contract,
      accessPolicyId,
      contractPolicyId,
      assetIds,
      _metadata: {
        ...(contract._metadata || {}),
        createdAt
      }
    };
  }

  private extractAssetIds(contract: any): string[] {
    const rawSelectors = contract.assetsSelector || contract['edc:assetsSelector'] || [];
    const selectors = Array.isArray(rawSelectors) ? rawSelectors : [rawSelectors];

    const ids: string[] = [];
    const pushId = (value: unknown) => {
      const scalar = this.extractScalarValue(value);
      if (typeof scalar === 'string' && scalar.trim().length > 0) {
        ids.push(scalar);
      }
    };

    selectors.forEach((selector: any) => {
      const rawOperandRight = selector?.operandRight ?? selector?.['edc:operandRight'];
      if (Array.isArray(rawOperandRight)) {
        rawOperandRight.forEach((value: unknown) => pushId(value));
      } else {
        pushId(rawOperandRight);
      }
    });

    return Array.from(new Set(ids));
  }

  private extractCreatedAt(contract: any): string | number | null {
    return (
      contract?._metadata?.createdAt ??
      contract?._metadata?.['edc:createdAt'] ??
      contract?.createdAt ??
      contract?.['edc:createdAt'] ??
      null
    );
  }

  private extractScalarValue(value: unknown): unknown {
    if (value && typeof value === 'object') {
      const obj = value as Record<string, unknown>;
      return obj['@value'] ?? obj['@id'] ?? obj['id'] ?? value;
    }
    return value;
  }
}
