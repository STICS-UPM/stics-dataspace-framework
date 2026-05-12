import { Component, OnInit, QueryList, ViewChildren } from '@angular/core';
import { AssetService } from "../../../shared/services/asset.service";
import { PolicyService } from "../../../shared/services/policy.service";
import { Asset, PolicyDefinition, ContractDefinitionInput, QuerySpec } from "../../../shared/models/edc-connector-entities";
import { NotificationService } from 'src/app/shared/services/notification.service';
import { ContractDefinitionService } from 'src/app/shared/services/contractDefinition.service';
import { BehaviorSubject, finalize, Observable, of, startWith, switchMap, tap } from 'rxjs';
import { Router } from '@angular/router';
import { FormControl, NgModel } from '@angular/forms';


@Component({
  selector: 'app-contract-definition-new',
  templateUrl: './contract-definition-new.component.html',
  styleUrls: ['./contract-definition-new.component.scss']
})
export class ContractDefinitionNewComponent implements OnInit {

  assetControl = new FormControl('');
  filteredAssets: Asset[] = [];
  selectedAssets: Asset[] = [];
  isLoading = false;
  policies: Array<PolicyDefinition> = [];
  availableAssets: Asset[] = [];
  name: string = '';
  editMode = false;
  accessPolicy?: PolicyDefinition;
  contractPolicy?: PolicyDefinition;
  contractDefinition: ContractDefinitionInput = {
    "@id": '',
    assetsSelector: [],
    accessPolicyId: undefined!,
    contractPolicyId: undefined!
  };
  private fetch$ = new BehaviorSubject(null);
  @ViewChildren(NgModel) formControls: QueryList<NgModel>;

  constructor(private policyService: PolicyService,
    private assetService: AssetService,
    private notificationService: NotificationService,
    private contractDefinitionService: ContractDefinitionService,
    private router: Router) {
  }

  ngOnInit(): void {
    this.policyService.queryAllPolicies().subscribe(policyDefinitions => {
      this.policies = policyDefinitions;
      this.accessPolicy = this.policies.find(policy => policy['@id'] === this.contractDefinition.accessPolicyId);
      this.contractPolicy = this.policies.find(policy => policy['@id'] === this.contractDefinition.contractPolicyId);
    });

    this.assetControl.valueChanges.pipe(
      startWith(''),
      tap(() => this.isLoading = true),
      switchMap(value => {
        const query = typeof value === 'string' ? value.trim() : '';
        const querySpec: QuerySpec = {
          offset: 0,
          limit: 50,
          filterExpression: [
            {
              operandLeft: 'id',
              operator: 'ilike',
              operandRight: `%${query}%`
            }
          ]
        };
        return this.assetService.requestAssets(querySpec)
        .pipe(
          finalize(() => this.isLoading = false)
        );
      })
    ).subscribe(results => {
      this.filteredAssets = results.filter(
        asset => !this.selectedAssets.some(sel => sel.id === asset.id)
      );

    });
  }

  displayAsset(asset: Asset): string {
    return asset ? asset.id : '';
  }

    addAsset(event: any, asset: Asset): void {
    if (event.isUserInput && !this.selectedAssets.find(a => a.id === asset.id)) {
      this.selectedAssets.push(asset);
      this.assetControl.setValue('');
    }
  }

  removeAsset(asset: Asset): void {
    this.selectedAssets = this.selectedAssets.filter(a => a.id !== asset.id);
  }

  onSave() {
    this.formControls.toArray().forEach(control => {
      control.control.markAsTouched();
    });

    if (!this.checkRequiredFields()) {
      this.notificationService.showError("Review required fields");
      return;
    }

    this.contractDefinition.accessPolicyId = this.accessPolicy['@id']!;
    this.contractDefinition.contractPolicyId = this.contractPolicy['@id']!;
    this.contractDefinition.assetsSelector = [];

    if (this.selectedAssets.length > 0) {
      const ids = this.selectedAssets.map(asset => asset.id);

      this.contractDefinition.assetsSelector = [...this.contractDefinition.assetsSelector, {
        operandLeft: 'https://w3id.org/edc/v0.0.1/ns/id',
        operator: 'in',
        operandRight: ids,
      }];
    }


    const newContractDefinition = this.contractDefinition;
    if (newContractDefinition) {
      this.contractDefinitionService.createContractDefinition(newContractDefinition)
        .subscribe({
          next: () => this.fetch$.next(null),
          error: () => this.notificationService.showError("Contract definition cannot be created"),
          complete: () => {
            this.navigateToContractDefinitions()
            this.notificationService.showInfo("Contract definition created")
          }
        });
    }
  }

  /**
   * Checks the required fields
   *
   * @returns true if required fields have been filled
   */
   private checkRequiredFields(): boolean {
    if (!this.contractDefinition['@id'] || !this.accessPolicy || !this.contractPolicy){
      return false;
    } else {
      return true;
    }
  }

  navigateToContractDefinitions(){
    this.router.navigate(['contract-definitions'])
  }
}
