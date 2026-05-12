import { ChangeDetectionStrategy, Component, OnInit } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { DataOffer } from '../../../shared/models/data-offer';
import { ASSET_TYPES } from 'src/app/shared/utils/app.constants';
import { FormGroup } from '@angular/forms';
import { Vocabulary } from 'src/app/shared/models/vocabulary';
import { QuerySpec } from '@think-it-labs/edc-connector-client';
import { CatalogBrowserService } from 'src/app/shared/services/catalog-browser.service';
import { ModelObserverApiService } from 'src/app/shared/services/model-observer/model-observer-api.service';
import { BehaviorSubject, switchMap } from 'rxjs';


@Component({
  selector: 'app-asset-details',
  templateUrl: './asset-details.component.html',
  styleUrls: ['./asset-details.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AssetDetailsComponent implements OnInit {

  private setting = {
    element: {
      dynamicDownload: null as HTMLElement
    }
  }

	private datasetSubject = new BehaviorSubject<DataOffer | null>(null);
  dataset$ = this.datasetSubject.asObservable();
  currentPage: number;
  pageSize: number;
  formValues: FormGroup[] = [];
  searchText: string = undefined;
  filterExpression: any[] = [];
  vocabulariesDefinition: Vocabulary[] = [];
  assetDataKeys: string[];
  assetDataEntries: { [key: string]: any[] } = {};
  queryParams: any;
	isNavigation: boolean = false;
	description: string;
	assetTypeIconClass: string;
	datasetTypeText: string;

  constructor(private router: Router,
              private activatedRoute: ActivatedRoute,
              private catalogService: CatalogBrowserService,
              private modelObserverApiService: ModelObserverApiService) {
								if (this.router.getCurrentNavigation()?.extras.state) {
									this.isNavigation = true;
									this.currentPage = this.router.getCurrentNavigation().extras.state.currentPage;
									this.pageSize = this.router.getCurrentNavigation().extras.state.pageSize;
									this.formValues = this.router.getCurrentNavigation().extras.state.formValues;
									this.searchText = this.router.getCurrentNavigation().extras.state.searchText;
									this.filterExpression = this.router.getCurrentNavigation().extras.state.filterExpression;
									this.vocabulariesDefinition = this.router.getCurrentNavigation().extras.state.vocabulariesDefinition;
								}
							}

  ngOnInit(): void {
    this.activatedRoute.paramMap.pipe(
      switchMap(params => {
        const participantId = String(params.get('participantId'));
        const datasetId = String(params.get('datasetId'));
        return this.loadDataset(participantId, datasetId);
      })
    ).subscribe();
  }

  loadDataset(participantId: any, datasetId: any) {
    const querySpec: QuerySpec = {
      offset: 0,
      limit: 1,
      sortField: "id",
      sortOrder: "ASC",
      filterExpression: [
        {
          operandLeft: "id",
          operator: "=",
          operandRight: datasetId
        },
        {
          operandLeft: "'properties'.'https://w3id.org/edc/v0.0.1/ns/participantId'",
          operator: "=",
          operandRight: participantId
        }
      ]
    };

    return this.catalogService.getPaginatedDataOffers(querySpec).pipe(
      switchMap(results => {
        const dataset = results.datasets[0];
        this.datasetSubject.next(dataset);
        this.assetDataKeys = Object.keys(dataset.properties.assetData);
        this.processAssetData(dataset);
				this.description = dataset.properties.description;
				this.processAsetType(dataset.properties.assetType)
        this.publishModelDetailViewed(dataset);
        return [];
      })
    );
  }

  private publishModelDetailViewed(dataset: DataOffer): void {
    if (!dataset || dataset.properties?.assetType !== ASSET_TYPES.machineLearning) {
      return;
    }

    this.modelObserverApiService.createEvent({
      eventType: 'MODEL_DETAIL_VIEWED',
      sourceComponent: 'inesdata-public-portal-frontend:asset-details',
      assetId: dataset.assetId,
      providerParticipantId: dataset.properties?.participantId || null,
      modelName: dataset.properties?.name || null,
      status: 'VIEWED',
      details: {
        participantId: this.activatedRoute.snapshot.paramMap.get('participantId'),
        datasetId: this.activatedRoute.snapshot.paramMap.get('datasetId')
      }
    }).subscribe({
      error: () => undefined
    });
  }

  isMachineLearningAsset(dataset: DataOffer): boolean {
    return dataset?.properties?.assetType === ASSET_TYPES.machineLearning;
  }

  openModelObserverTimeline(dataset: DataOffer): void {
    if (!dataset?.assetId) {
      return;
    }

    this.router.navigate(['/model-observer/timeline', dataset.assetId]);
  }

  openParticipantObserverSummary(dataset: DataOffer): void {
    const participantId = `${dataset?.properties?.participantId || ''}`.trim();
    if (!participantId) {
      return;
    }

    this.router.navigate(['/model-observer/participants', participantId]);
  }

  processAssetData(dataset: DataOffer) {
    this.assetDataKeys = this.assetDataKeys.filter(key => {
      const entries = this.getEntries(dataset.properties.assetData[key]);

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

	goBack(): void {
		this.router.navigate(['/catalog'], {
			state: {
				currentPage: this.currentPage,
				pageSize: this.pageSize,
				formValues: this.formValues,
				searchText: this.searchText,
				filterExpression: this.filterExpression,
				vocabulariesDefinition: this.vocabulariesDefinition
			}
		});
	}

	processAsetType(assetType: string) {
		if (ASSET_TYPES.machineLearning === assetType) {
			this.assetTypeIconClass = 'pi-machinelearning';
			this.datasetTypeText = 'Machine learning';
		} else if (ASSET_TYPES.service === assetType) {
			this.assetTypeIconClass = 'pi-briefcase';
			this.datasetTypeText = 'Servicio';
		} else {
			this.assetTypeIconClass = 'pi-box';
			this.datasetTypeText = 'Dataset';
		}
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

	dynamicDownloadAssetJson(dataset: DataOffer) {
		if (!this.setting.element.dynamicDownload) {
			this.setting.element.dynamicDownload = document.createElement('a');
		}
		const element = this.setting.element.dynamicDownload;
		const fileType = 'text/json';
		const jsonContent = {
			"http://www.w3.org/ns/dcat#dataset": dataset.originalJson,
			"@context": dataset.context
		}
		const jsonContentString = JSON.stringify(jsonContent, null, 2);
		element.setAttribute('href', `data:${fileType};charset=utf-8,${encodeURIComponent(jsonContentString)}`);
		element.setAttribute('download', dataset.properties.id + '.json');

		var event = new MouseEvent("click");
		element.dispatchEvent(event);
	}
}
