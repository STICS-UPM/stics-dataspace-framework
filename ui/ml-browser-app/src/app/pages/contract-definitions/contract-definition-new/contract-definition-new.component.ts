import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { FormControl, ReactiveFormsModule, FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatAutocompleteSelectedEvent } from '@angular/material/autocomplete';
import { startWith, switchMap, finalize, tap } from 'rxjs/operators';
import { Observable } from 'rxjs';

import { PolicyService } from '../../../shared/services/policy.service';
import { ContractDefinitionService } from '../../../shared/services/contract-definition.service';
import { ContractSequenceService } from '../../../shared/services/contract-sequence.service';
import { MlAssetsService } from '../../../shared/services/ml-assets.service';
import { NotificationService } from '../../../shared/services/notification.service';
import { AuthService } from '../../../shared/services/auth.service';
import { MLAsset } from '../../../shared/models/ml-asset';
import { PolicyDefinition, ContractDefinitionInput } from '@think-it-labs/edc-connector-client';
import { PolicyCreateDialogComponent } from '../policy-create-dialog/policy-create-dialog.component';

@Component({
  selector: 'app-contract-definition-new',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    FormsModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatAutocompleteModule,
    MatDialogModule,
    MatTooltipModule
  ],
  templateUrl: './contract-definition-new.component.html',
  styleUrl: './contract-definition-new.component.scss'
})
export class ContractDefinitionNewComponent implements OnInit {
  private readonly policyService = inject(PolicyService);
  private readonly contractSequenceService = inject(ContractSequenceService);
  private readonly assetService = inject(MlAssetsService);
  private readonly contractDefinitionService = inject(ContractDefinitionService);
  private readonly notificationService = inject(NotificationService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);

  assetControl = new FormControl('');
  filteredAssets: MLAsset[] = [];
  selectedAssets: MLAsset[] = [];
  isLoading = false;
  isAllocatingId = false;
  private contractIdUser = '';
  private contractIdIndex = 0;
  
  policies: PolicyDefinition[] = [];
  accessPolicy?: PolicyDefinition;
  contractPolicy?: PolicyDefinition;

  contractDefinition: ContractDefinitionInput = {
    '@id': '',
    assetsSelector: [],
    accessPolicyId: '',
    contractPolicyId: ''
  };

  ngOnInit(): void {
    this.initializeContractDefinitionId();

    // Load pre-selected asset if navigated from ML Browser
    const navigation = this.router.getCurrentNavigation();
    const state = navigation?.extras?.state || (history.state && history.state.preSelectedAssetId ? history.state : null);
    const preSelectedAssetId = state?.['preSelectedAssetId'];

    if (preSelectedAssetId) {
      console.log('[Contract Definition New] Pre-selected asset ID:', preSelectedAssetId);
      this.loadPreSelectedAsset(preSelectedAssetId);
    }

    // Load available policies and ensure default template exists
    this.loadPolicies();

    // Setup asset autocomplete
    this.assetControl.valueChanges.pipe(
      startWith(''),
      tap(() => this.isLoading = true),
      switchMap(value => {
        const query = typeof value === 'string' ? value.trim() : '';
        
        if (!query) {
          return this.getLocalAssets();
        }
        
        // Filter local assets by search term
        return this.getLocalAssets().pipe(
          switchMap(assets => {
            const filtered = assets.filter(asset => 
              asset.id.toLowerCase().includes(query.toLowerCase()) ||
              asset.name.toLowerCase().includes(query.toLowerCase())
            );
            return [filtered];
          })
        );
      }),
      finalize(() => this.isLoading = false)
    ).subscribe({
      next: (assets) => {
        // Exclude already selected assets
        this.filteredAssets = assets.filter(asset => 
          !this.selectedAssets.find(selected => selected.id === asset.id)
        );
      },
      error: (error) => {
        console.error('[Contract Definition New] Error loading assets:', error);
        this.filteredAssets = [];
      }
    });
  }

  /**
   * Load pre-selected asset from ML Browser
   */
  private loadPreSelectedAsset(assetId: string): void {
    this.getLocalAssets().subscribe({
      next: (assets) => {
        const asset = assets.find(a => a.id === assetId);
        if (asset) {
          this.selectedAssets = [asset];
          console.log('[Contract Definition New] Pre-selected asset loaded:', asset.name);
        } else {
          console.warn('[Contract Definition New] Pre-selected local asset not found:', assetId);
          this.notificationService.showError('Only local assets can be assigned to contract definitions.');
        }
      },
      error: (error) => {
        console.error('[Contract Definition New] Error loading pre-selected asset:', error);
      }
    });
  }

  displayAsset(asset: MLAsset | null): string {
    return asset ? asset.id : '';
  }

  onAssetSelected(event: MatAutocompleteSelectedEvent): void {
    const asset = event.option.value as MLAsset;
    if (!asset) {
      return;
    }

    if (!asset.isLocal) {
      this.notificationService.showError('Only local assets can be assigned to contract definitions.');
      this.assetControl.setValue('');
      return;
    }

    if (!this.selectedAssets.find(a => a.id === asset.id)) {
      this.selectedAssets.push(asset);
    }
    this.assetControl.setValue('');
  }

  removeAsset(asset: MLAsset): void {
    const index = this.selectedAssets.findIndex(a => a.id === asset.id);
    if (index >= 0) {
      this.selectedAssets.splice(index, 1);
    }
  }

  onSave(): void {
    if (!this.checkRequiredFields()) {
      this.notificationService.showError('Please fill all required fields');
      return;
    }

    if (this.selectedAssets.some(asset => !asset.isLocal)) {
      this.notificationService.showError('Contract definitions can only include local assets.');
      return;
    }

    if (!this.contractDefinition['@id']) {
      this.notificationService.showError('Contract definition ID is not ready yet');
      return;
    }
    this.isAllocatingId = true;
    this.createContractDefinition();
  }

  private checkRequiredFields(): boolean {
    return !!(
      this.accessPolicy && 
      this.contractPolicy
    );
  }

  navigateToContractDefinitions(): void {
    this.router.navigate(['/ml-assets']);
  }

  cancel(): void {
    this.router.navigate(['/ml-assets']);
  }

  /**
   * Open dialog to create a new access policy
   */
  createAccessPolicy(): void {
    const dialogRef = this.dialog.open(PolicyCreateDialogComponent, {
      width: '700px',
      disableClose: false
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        // Reload policies and select the newly created one
        this.loadPolicies(result['@id']);
      }
    });
  }

  /**
   * Open dialog to create a new contract policy
   */
  createContractPolicy(): void {
    const dialogRef = this.dialog.open(PolicyCreateDialogComponent, {
      width: '700px',
      disableClose: false
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        // Reload policies and select the newly created one
        this.loadPolicies(undefined, result['@id']);
      }
    });
  }

  /**
   * Load policies from backend and optionally select specific ones
   */
  private loadPolicies(selectAccessPolicyId?: string, selectContractPolicyId?: string): void {
    this.policyService.queryAllPolicies().subscribe({
      next: (policies) => {
        this.policies = policies;
        this.ensureDefaultOpenPolicy(policies, selectAccessPolicyId, selectContractPolicyId);
        
        if (selectAccessPolicyId) {
          this.accessPolicy = policies.find(p => p['@id'] === selectAccessPolicyId);
        }
        
        if (selectContractPolicyId) {
          this.contractPolicy = policies.find(p => p['@id'] === selectContractPolicyId);
        }
      },
      error: (error) => {
        console.error('[Contract Definition New] Error reloading policies:', error);
      }
    });
  }

  private getLocalAssets(): Observable<MLAsset[]> {
    return this.assetService.getMachinelearningAssets({ assetSources: ['Local Asset'] });
  }

  private createContractDefinition(): void {
    this.contractDefinition.accessPolicyId = this.accessPolicy!['@id']!;
    this.contractDefinition.contractPolicyId = this.contractPolicy!['@id']!;
    this.contractDefinition.assetsSelector = [];

    if (this.selectedAssets.length > 0) {
      const ids = this.selectedAssets.map(asset => asset.id);
      this.contractDefinition.assetsSelector = [{
        operandLeft: 'https://w3id.org/edc/v0.0.1/ns/id',
        operator: 'in',
        operandRight: ids,
      }];
    }

    console.log('[Contract Definition New] Creating contract definition:', this.contractDefinition);
    this.contractDefinitionService.createContractDefinition(this.contractDefinition).subscribe({
      next: () => {
        this.contractSequenceService.commitContractDefinitionId(this.contractIdUser, this.contractIdIndex).subscribe({
          next: () => {
            this.notificationService.showInfo('Contract definition created successfully');
            this.navigateToContractDefinitions();
          },
          error: (error) => {
            console.error('[Contract Definition New] Contract created but failed to commit sequence index:', error);
            this.notificationService.showInfo('Contract created, but sequence commit failed. Refresh before creating another.');
            this.navigateToContractDefinitions();
          }
        });
      },
      error: (error) => {
        console.error('[Contract Definition New] Error creating contract definition:', error);
        const errorMsg = error?.error?.message || error?.message || 'Unknown error';
        this.notificationService.showError(`Contract definition cannot be created: ${errorMsg}`);
      },
      complete: () => {
        this.isAllocatingId = false;
      }
    });
  }

  private ensureDefaultOpenPolicy(policies: PolicyDefinition[], selectAccessPolicyId?: string, selectContractPolicyId?: string): void {
    const defaultPolicyId = `${this.authService.getCurrentUser()?.connectorId || this.authService.getUserRole() || 'user'}~default-open-policy`;
    const existing = policies.find(p => p['@id'] === defaultPolicyId);
    if (existing) {
      if (!this.accessPolicy && !selectAccessPolicyId) {
        this.accessPolicy = existing;
      }
      if (!this.contractPolicy && !selectContractPolicyId) {
        this.contractPolicy = existing;
      }
      return;
    }

    const defaultPolicy = {
      '@id': defaultPolicyId,
      policy: {
        '@context': 'http://www.w3.org/ns/odrl.jsonld',
        '@type': 'Set',
        permission: [],
        prohibition: [],
        obligation: []
      }
    };

    this.policyService.createPolicy(defaultPolicy as any).subscribe({
      next: () => {
        this.loadPolicies(defaultPolicyId, defaultPolicyId);
      },
      error: (error) => {
        console.error('[Contract Definition New] Error creating default open policy:', error);
      }
    });
  }

  private initializeContractDefinitionId(): void {
    const userId = this.authService.getCurrentUser()?.connectorId || this.authService.getUserRole() || 'user';
    this.contractIdUser = userId;
    this.contractSequenceService.peekNextContractDefinitionId(userId).subscribe({
      next: (result) => {
        this.contractIdUser = result.userId;
        this.contractIdIndex = result.index;
        this.contractDefinition['@id'] = result.contractDefinitionId;
      },
      error: (error) => {
        console.error('[Contract Definition New] Error peeking contract ID:', error);
        this.notificationService.showError('Failed to prepare contract definition ID');
      }
    });
  }
}
