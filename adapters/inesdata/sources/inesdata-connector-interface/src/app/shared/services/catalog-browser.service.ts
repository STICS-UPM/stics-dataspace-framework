import { HttpClient, HttpErrorResponse, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { EMPTY, from, lastValueFrom, Observable } from 'rxjs';
import { catchError, map, reduce } from 'rxjs/operators';
import { DataOffer } from '../models/data-offer';
import { ContractNegotiationService } from './contractNegotiation.service';
import { TransferProcessService } from './transferProcess.service';
import { environment } from "src/environments/environment";

import {
  ContractNegotiationRequest,
  ContractNegotiation,
  TransferProcess,
  TransferProcessInput,
} from "../models/edc-connector-entities";
import { JSON_LD_DEFAULT_CONTEXT, QuerySpec } from '@think-it-labs/edc-connector-client';



/**
 * Combines several services that are used from the {@link CatalogBrowserComponent}
 */
@Injectable({
  providedIn: 'root'
})
export class CatalogBrowserService {

  private readonly BASE_URL = `${environment.runtime.catalogUrl}`;

  constructor(private httpClient: HttpClient,
    private transferProcessService: TransferProcessService,
    private negotiationService: ContractNegotiationService) {
  }

  /**
   * Gets all data offers (datasets) according to a particular query
   * @param querySpec
   */
  getPaginatedDataOffers(querySpec: QuerySpec): Observable<DataOffer[]> {
    let body;

    if (querySpec) {
      body = {
        ...querySpec,
        "@context": JSON_LD_DEFAULT_CONTEXT,
      }
    }

    return this.httpClient.post<Array<any>>(`${this.BASE_URL}${environment.runtime.service.federatedCatalog.paginationRequest}`, body)
      .pipe(map(catalogs => catalogs.map(catalog => this.mapCatalog(catalog))), reduce((acc, val) => {
        for (const subArray of val) {
          for (const item of subArray) {
            acc.push(item);
          }
        }
        return acc;
      }, new Array<DataOffer>()));
  }

  /**
   * Gets all data offers (datasets)
   */
   getDataOffers(): Observable<DataOffer[]> {
    return this.post<Array<any>>(`${this.BASE_URL}`)
      .pipe(map(catalogs => catalogs.map(catalog => this.mapCatalog(catalog))), reduce((acc, val) => {
        for (const subArray of val) {
          for (const item of subArray) {
            acc.push(item);
          }
        }
        return acc;
      }, new Array<DataOffer>()));
  }

  initiateTransfer(transferRequest: TransferProcessInput): Observable<string> {
    return this.transferProcessService.initiateTransfer(transferRequest).pipe(map(t => t.id))
  }

  getTransferProcessesById(id: string): Observable<TransferProcess> {
    return this.transferProcessService.getTransferProcess(id);
  }

  initiateNegotiation(initiate: ContractNegotiationRequest): Observable<string> {
    return this.negotiationService.initiateContractNegotiation(initiate).pipe(map(t => t.id))
  }

  getNegotiationState(id: string): Observable<ContractNegotiation> {
    return this.negotiationService.getNegotiation(id);
  }

  /**
  * Gets the total number of datasets (federated catalog)
  */
  count(){
    const querySpec: QuerySpec = {
      filterExpression: []
    }

    const body = {
      "@context": JSON_LD_DEFAULT_CONTEXT,
      ...querySpec
    };

    return from(lastValueFrom(this.httpClient.post<number>(
      `${environment.runtime.managementApiUrl}${environment.runtime.service.federatedCatalog.count}`, body
    )));
  }

  private post<T>(urlPath: string,
    params?: HttpParams | { [param: string]: string | number | boolean | ReadonlyArray<string | number | boolean>; })
    : Observable<T> {
    const url = `${urlPath}`;
    let headers = new HttpHeaders({ "Content-type": "application/json" });
    return this.catchError(this.httpClient.post<T>(url, "{\"edc:operandLeft\": \"\",\"edc:operandRight\": \"\",\"edc:operator\": \"\",\"edc:Criterion\":\"\"}", { headers, params }), url, 'POST');
  }

  private catchError<T>(observable: Observable<T>, url: string, method: string): Observable<T> {
    return observable
      .pipe(
        catchError((httpErrorResponse: HttpErrorResponse) => {
          if (httpErrorResponse.error instanceof Error) {
            console.error(`Error accessing URL '${url}', Method: 'GET', Error: '${httpErrorResponse.error.message}'`);
          } else {
            console.error(`Unsuccessful status code accessing URL '${url}', Method: '${method}', StatusCode: '${httpErrorResponse.status}', Error: '${httpErrorResponse.error?.message}'`);
          }

          return EMPTY;
        }));
  }

  private mapCatalog(catalog: any) {
    const arr = Array<DataOffer>();
    let datasets = catalog["http://www.w3.org/ns/dcat#dataset"];
    if (!datasets) {
      return arr;
    }

    if (!Array.isArray(datasets)) {
      datasets = [datasets];
    }

    for (const dataset of datasets) {
      const properties: { [key: string]: any; } = {
				id: this.firstDatasetValue(dataset, ['id', '@id']),
				name: this.firstDatasetValue(dataset, ['name', 'dcterms:title', 'http://purl.org/dc/terms/title']),
				version: this.firstDatasetValue(dataset, ['version']),
				assetType: this.firstDatasetValue(dataset, ['assetType', 'edc:assetType', 'https://w3id.org/edc/v0.0.1/ns/assetType']),
				contenttype: this.firstDatasetValue(dataset, ['contenttype', 'edc:contenttype', 'https://w3id.org/edc/v0.0.1/ns/contenttype', 'dcat:mediaType', 'http://www.w3.org/ns/dcat#mediaType']),
				assetData: this.firstDatasetValue(dataset, ['assetData', 'edc:assetData', 'https://w3id.org/edc/v0.0.1/ns/assetData']),
				description: this.firstDatasetValue(dataset, ['description', 'dcterms:description', 'http://purl.org/dc/terms/description']),
				shortDescription: this.firstDatasetValue(dataset, ['shortDescription', 'edc:shortDescription', 'https://w3id.org/edc/v0.0.1/ns/shortDescription']),
				byteSize: this.firstDatasetValue(dataset, ['http://www.w3.org/ns/dcat#byteSize', 'byteSize']),
				format: this.firstDatasetValue(dataset, ['format', 'dcterms:format', 'http://purl.org/dc/terms/format']),
				keywords: this.firstDatasetValue(dataset, ['keywords', 'dcat:keyword', 'http://www.w3.org/ns/dcat#keyword']),
        participantId: this.firstDatasetValue(dataset, ['participantId', 'originator', 'dspace:participantId']),
        storageType: this.findStorageType(dataset),
        fileName: this.findFileName(dataset),
        path: this.findHttpPath(dataset),
        method: this.firstDatasetValue(dataset, ['method', 'edc:method', 'https://w3id.org/edc/v0.0.1/ns/method'])
			}
      const assetId = dataset["@id"];

      const contractOffers = dataset["odrl:hasPolicy"];

      const endpointUrl = this.findEndpointUrl(dataset, catalog);

      const dataOffer = {
        assetId: assetId,
        properties: properties,
        endpointUrl: endpointUrl,
        contractOffers: contractOffers,
        originator: catalog["originator"],
      }

      arr.push(dataOffer);
    }
    return arr;
  }

  private findEndpointUrl(dataset: any, catalog: any) {
    const distributions = dataset['http://www.w3.org/ns/dcat#distribution'];
    const distributionList = Array.isArray(distributions) ? distributions : distributions ? [distributions] : [];
    const accessService = distributionList[0]?.['http://www.w3.org/ns/dcat#accessService'];
    const serviceId = this.resolveTextValue(accessService?.['@id']);

    const services = catalog['http://www.w3.org/ns/dcat#service'];
    const serviceList = Array.isArray(services) ? services : services ? [services] : [];

    if (!serviceId) {
      return this.resolveTextValue(serviceList[0]?.['http://www.w3.org/ns/dcat#endpointUrl']);
    }

    const service = serviceList.find(candidate => candidate?.['@id'] === serviceId);
    return this.resolveTextValue(service?.['http://www.w3.org/ns/dcat#endpointUrl']);
  }

  private findStorageType(dataset: any): string {
    const distributions = dataset?.['http://www.w3.org/ns/dcat#distribution'];
    const distributionList = Array.isArray(distributions) ? distributions : distributions ? [distributions] : [];
    const datasetStorageType = this.resolveTextValue(dataset?.storageType)
      || this.resolveTextValue(dataset?.['edc:dataAddressType'])
      || this.resolveTextValue(dataset?.['https://w3id.org/edc/v0.0.1/ns/dataAddressType'])
      || this.resolveTextValue(dataset?.type)
      || this.resolveTextValue(dataset?.['edc:type']);

    if (datasetStorageType) {
      return datasetStorageType;
    }

    for (const distribution of distributionList) {
      const accessService = distribution?.['http://www.w3.org/ns/dcat#accessService'] || {};
      const distributionStorageType = this.resolveTextValue(distribution?.storageType)
        || this.resolveTextValue(distribution?.['edc:dataAddressType'])
        || this.resolveTextValue(distribution?.['https://w3id.org/edc/v0.0.1/ns/dataAddressType'])
        || this.resolveTextValue(distribution?.type)
        || this.resolveTextValue(distribution?.['edc:type'])
        || this.resolveTextValue(distribution?.['http://purl.org/dc/terms/format'])
        || this.resolveTextValue(distribution?.['http://www.w3.org/ns/dcat#mediaType'])
        || this.resolveTextValue(accessService?.storageType)
        || this.resolveTextValue(accessService?.['edc:dataAddressType'])
        || this.resolveTextValue(accessService?.type)
        || this.resolveTextValue(accessService?.['http://purl.org/dc/terms/format'])
        || this.resolveTextValue(accessService?.['http://www.w3.org/ns/dcat#mediaType']);

      if (distributionStorageType) {
        return distributionStorageType;
      }
    }

    return '';
  }

  private findFileName(dataset: any): string {
    const distributions = dataset?.['http://www.w3.org/ns/dcat#distribution'];
    const distributionList = Array.isArray(distributions) ? distributions : distributions ? [distributions] : [];
    const firstDistribution = distributionList[0] || {};

    return this.resolveTextValue(firstDistribution.fileName)
      || this.resolveTextValue(firstDistribution.filename)
      || this.resolveTextValue(firstDistribution.keyName)
      || this.resolveTextValue(firstDistribution.s3Key)
      || this.resolveTextValue(dataset?.fileName)
      || '';
  }

  private findHttpPath(dataset: any): string {
    return this.resolveTextValue(dataset?.path)
      || this.resolveTextValue(dataset?.['edc:path'])
      || this.resolveTextValue(dataset?.['https://w3id.org/edc/v0.0.1/ns/path'])
      || this.resolveTextValue(dataset?.proxyPath)
      || this.resolveTextValue(dataset?.['edc:proxyPath'])
      || this.resolveTextValue(dataset?.['https://w3id.org/edc/v0.0.1/ns/proxyPath'])
      || '';
  }

  private firstDatasetValue(dataset: any, keys: string[]): any {
    for (const key of keys) {
      const value = dataset?.[key];
      if (value !== undefined && value !== null && value !== '') {
        return value;
      }
    }

    return '';
  }

  private resolveTextValue(value: any): string {
    if (value === undefined || value === null) {
      return '';
    }

    if (Array.isArray(value)) {
      for (const item of value) {
        const resolved = this.resolveTextValue(item);
        if (resolved) {
          return resolved;
        }
      }
      return '';
    }

    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      return `${value}`.trim();
    }

    if (typeof value !== 'object') {
      return '';
    }

    if (value['@value'] !== undefined) {
      return this.resolveTextValue(value['@value']);
    }

    if (value['@id'] !== undefined && Object.keys(value).length === 1) {
      return this.resolveTextValue(value['@id']);
    }

    for (const nestedValue of Object.values(value)) {
      const resolved = this.resolveTextValue(nestedValue);
      if (resolved) {
        return resolved;
      }
    }

    return '';
  }
}
