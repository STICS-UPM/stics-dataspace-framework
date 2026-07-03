import { Component, Inject } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { TransferProcessStates } from "../../../shared/models/transfer-process-states";
import { NegotiationResult } from "../../../shared/models/negotiation-result";
import { ContractNegotiation, ContractNegotiationRequest, Policy } from "../../../shared/models/edc-connector-entities";
import { CatalogBrowserService } from 'src/app/shared/services/catalog-browser.service';
import { NotificationService } from 'src/app/shared/services/notification.service';
import { StorageType } from 'src/app/shared/models/storage-type';
import { PolicyCard } from '../../../shared/models/policy/policy-card';
import { DATA_ADDRESS_TYPES } from '../../../shared/utils/app.constants';
import { PolicyCardBuilder } from 'src/app/shared/models/policy/policy-card-builder';
import { JsonDialogData } from '../../json-dialog/json-dialog/json-dialog.data';
import { JsonDialogComponent } from '../../json-dialog/json-dialog/json-dialog.component'
import { PolicyBuilder } from '@think-it-labs/edc-connector-client';
import { Router } from '@angular/router';
import { catchError, filter, from, interval, of, switchMap, takeUntil, tap, timer } from 'rxjs';

export interface ContractOffersDialogData {
  assetId: string;
  contractOffers?: any;
  endpointUrl?: string;
  properties: any;
  privateProperties: any;
  dataAddress?: any;
  isCatalogView: boolean;
  returnUrl?: string;
  startTab?: 'details' | 'offers';
}

interface RunningTransferProcess {
  processId: string;
  assetId?: string;
  state: TransferProcessStates;
}

interface Offer {
  policyCard: PolicyCard,
  policy: Policy;
}

@Component({
  selector: 'contract-offers-viewer',
  templateUrl: './contract-offers-viewer.component.html',
  styleUrls: ['./contract-offers-viewer.component.scss']
})
export class ContractOffersViewerComponent {

  runningTransferProcesses: RunningTransferProcess[] = [];
  runningNegotiations: Map<string, NegotiationResult> = new Map<string, NegotiationResult>();
  finishedNegotiations: Map<string, ContractNegotiation> = new Map<string, ContractNegotiation>();
  assetDataKeys: string[];
  assetDataEntries: { [key: string]: any[] } = {};
  dataAddressType: string;
  policyCards: PolicyCard[] = [];
  offers: Offer[] = [];
  data: ContractOffersDialogData= undefined;
  selectedMainTabIndex = 0;
  private pollingHandleNegotiation?: any;

  constructor(@Inject('STORAGE_TYPES') public storageTypes: StorageType[],
    private apiService: CatalogBrowserService, private notificationService: NotificationService,
    private policyCardBuilder: PolicyCardBuilder,
    private readonly dialog: MatDialog,
    private router: Router) {
    this.data = undefined
    this.data = this.router.getCurrentNavigation()?.extras.state?.assetDetailData
      ?? history.state?.assetDetailData;

    if (!this.data) {
      this.notificationService.showWarning('Asset details are no longer available. Please open it again from the list.');
      this.router.navigate(['/catalog']);
      return;
    }

    if (this.data.isCatalogView && this.data.startTab === 'offers') {
      this.selectedMainTabIndex = 1;
    }

    const assetData = this.data?.properties?.assetData ?? {};
    this.assetDataKeys = Object.keys(assetData);
    this.processAssetData();

    if (this.data.contractOffers) {
      this.processPolicies();
    }

    if (this.data.dataAddress) {
      if (this.data.privateProperties) {
        this.dataAddressType = this.getDataAddressName(DATA_ADDRESS_TYPES.inesDataStore);
      } else {
        this.dataAddressType = this.getDataAddressName(this.data.dataAddress.type);
        delete this.data.dataAddress['@type'];
      }
    }

  }
  processPolicies() {
    if(this.isArray(this.data.contractOffers)) {
      for (const contractOffer of this.data.contractOffers) {
        const parsedComplexPolicy = this.convertExpressionsToArray(contractOffer.complexPolicy);
        this.offers.push({
          policyCard: this.policyCardBuilder.buildPolicyCardFromContractOffer(parsedComplexPolicy),
          policy: new PolicyBuilder()
              .raw({
                ...contractOffer.offer,
                target: this.data.assetId,
                assigner: this.data.properties.participantId
              })
              .build()
        })
      }
    } else {
      const parsedComplexPolicy = this.convertExpressionsToArray(this.data.contractOffers.complexPolicy);
      this.offers.push({
        policyCard: this.policyCardBuilder.buildPolicyCardFromContractOffer(parsedComplexPolicy),
        policy: new PolicyBuilder()
            .raw({
              ...this.data.contractOffers.offer,
              target: this.data.assetId,
              assigner: this.data.properties.participantId
            })
            .build()
      })
    }

  }

  getDataAddressName(dataAddressTypeId: string) {
    const normalizedId = this.normalizeDataAddressTypeId(dataAddressTypeId);
    const foundObject = this.storageTypes.find(item => item.id === normalizedId);
    return foundObject ? foundObject.name : normalizedId;
}

  private normalizeDataAddressTypeId(dataAddressTypeId: string): string {
    const normalized = `${dataAddressTypeId || ''}`.trim();
    const lower = normalized.toLowerCase();

    if (lower.includes('http')) {
      return DATA_ADDRESS_TYPES.httpData;
    }

    if (lower.includes('amazon') || lower.includes('s3')) {
      return DATA_ADDRESS_TYPES.amazonS3;
    }

    if (lower.includes('inesdatastore')) {
      return DATA_ADDRESS_TYPES.inesDataStore;
    }

    return normalized;
  }

  processAssetData() {
    this.assetDataKeys = this.assetDataKeys.filter(key => {
      const assetData = this.data?.properties?.assetData ?? {};
      const entries = this.getEntries(assetData[key]);

      if (entries.length === 0) {
        return false;
      }

      this.assetDataEntries[key] = entries.map(item => ({
        key: item.key,
        value: item.value,
        isObject: this.isObject(item.value),
        isArray: this.isArray(item.value),
        entries: this.isObject(item.value) ? this.getEntries(item.value) : null
      }));

      return true;
    });
  }

  hasDetailedInformation() {
    return this.data && this.data.properties && this.data.properties.assetData &&
      Object.keys(this.data.properties.assetData).length > 0;
  }

  getEntries(obj: any): { key: string, value: any }[] {
    return Object.entries(obj || {}).map(([key, value]) => ({ key, value }));
  }

  isObject(value: any): boolean {
    return value && typeof value === 'object' && !Array.isArray(value);
  }

  isArray(value: any): boolean {
    return Array.isArray(value);
  }

  containsOnlyObjects(array: any[]): boolean {
    return array.every(item => this.isObject(item));
  }

  isBusy(contractOffer: Policy) {
    return this.runningNegotiations.get(contractOffer["@id"]) !== undefined || !!this.runningTransferProcesses.find(tp => tp.assetId === contractOffer.assetId);
  }

  getState(contractOffer: Policy): string {
    const transferProcess = this.runningTransferProcesses.find(tp => tp.assetId === contractOffer.assetId);
    if (transferProcess) {
      return TransferProcessStates[transferProcess.state];
    }

    const negotiation = this.runningNegotiations.get(contractOffer["@id"]);
    if (negotiation) {
      return 'negotiating';
    }

    return '';
  }

  isNegotiated(contractOffer: Policy) {
    return this.finishedNegotiations.get(contractOffer.id) !== undefined;
  }

  onNegotiateClicked(contractOffer: Policy) {
    const initiateRequest: ContractNegotiationRequest = {
      counterPartyAddress: this.data.endpointUrl,
      policy: contractOffer
    };

    this.apiService.initiateNegotiation(initiateRequest).subscribe(negotiationId => {
      this.finishedNegotiations.delete(initiateRequest.policy["@id"]);
      this.runningNegotiations.set(initiateRequest.policy["@id"], {
        id: negotiationId,
        offerId: initiateRequest.policy["@id"]
      });

      this.checkActiveNegotiations(negotiationId, initiateRequest.policy["@id"]);
    }, error => {
      console.error(error);
      this.notificationService.showError("Error starting negotiation");
    });
  }

  checkActiveNegotiations(negotiationId: string, offerId: string) {
    const timeout$ = timer(30000).pipe(
      tap(() => {
        if (this.runningNegotiations.has(offerId)) {
          this.notificationService.showWarning(
            `Negotiation [${negotiationId}] timed out after 30 seconds.`
          );
          this.runningNegotiations.delete(offerId);
        }
      })
    );

    this.pollingHandleNegotiation = interval(2000).pipe(
      takeUntil(timeout$),
      switchMap(() => from([...this.runningNegotiations.values()])),
      switchMap(negotiation =>
        this.apiService.getNegotiationState(negotiation.id).pipe(
          catchError(error => {
            console.error("Polling error:", error);
            this.notificationService.showError("Error polling negotiation");
            this.runningNegotiations.delete(negotiation.offerId);
            return of(null);
          })
        )
      ),
      filter(updatedNegotiation => updatedNegotiation !== null),
      tap(updatedNegotiation => {
        const finishedStates = ["VERIFIED", "TERMINATED", "FINALIZED", "ERROR"];
        if (finishedStates.includes(updatedNegotiation.state)) {
            this.runningNegotiations.delete(offerId);

          if (updatedNegotiation.state === "VERIFIED" || updatedNegotiation.state === "FINALIZED") {
            this.finishedNegotiations.set(offerId, updatedNegotiation);
            this.notificationService.showInfo("Contract Negotiation complete!");
          } else if (updatedNegotiation.state === "TERMINATED") {
            const errorDetail = updatedNegotiation.optionalValue("edc", "errorDetail");
            if (typeof errorDetail === 'string' && errorDetail.includes("Contract offer is not valid")) {
              this.finishedNegotiations.set(offerId, updatedNegotiation);
              this.notificationService.showError("Contract offer is not valid.");
            }
          }

          if (this.runningNegotiations.size === 0) {
            this.cleanupPolling();
          }
        }
      })
    ).subscribe();
  }

  private cleanupPolling() {
    this.pollingHandleNegotiation?.unsubscribe();
    this.pollingHandleNegotiation = undefined;
  }

  getJsonPolicy(policy: Policy): any {
    return {
      permission: policy['odrl:permission'],
      prohibition: policy['odrl:prohibition'],
      obligation: policy['odrl:obligation']
    }
  }

  onPolicyDetailClick(policyCard: PolicyCard) {
    const data: JsonDialogData = {
      title: "Contract Policy JSON-LD",
      subtitle: this.data.assetId,
      icon: 'policy',
      objectForJson: policyCard.objectForJson
    };

    this.dialog.open(JsonDialogComponent, {data});
  }

  convertExpressionsToArray(obj: any): any {
    if (Array.isArray(obj)) {
      return obj.map((element) => this.convertExpressionsToArray(element));
    } else if (obj !== null && typeof obj === 'object') {
      const newObj: any = {};

      for (const key in obj) {
        if (obj.hasOwnProperty(key)) {
          if (key === 'expressions') {
            if (!Array.isArray(obj[key])) {
              newObj[key] = [this.convertExpressionsToArray(obj[key])];
            } else {
              newObj[key] = obj[key].map((item: any) => this.convertExpressionsToArray(item));
            }
          } else {
            newObj[key] = this.convertExpressionsToArray(obj[key]);
          }
        }
      }

      return newObj;
    } else {
      return obj;
    }
  }

  backToList(){
    this.router.navigate([this.data.returnUrl])
  }
}
