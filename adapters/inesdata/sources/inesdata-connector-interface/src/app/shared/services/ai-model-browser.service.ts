import { Injectable } from '@angular/core';
import { forkJoin, Observable, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { environment } from 'src/environments/environment';
import { AiModelBrowserItem, AiModelBrowserSource } from '../models/ai-model-browser-item';
import {
  Asset,
  ContractDefinition,
  QuerySpec
} from '../models/edc-connector-entities';
import { DataOffer } from '../models/data-offer';
import { AssetService } from './asset.service';
import { CatalogBrowserService } from './catalog-browser.service';
import { ContractDefinitionService } from './contractDefinition.service';

export interface AiModelBrowserQuery {
  searchTerm?: string;
  sources?: AiModelBrowserSource[];
  tasks?: string[];
  taskTypes?: string[];
  modalities?: string[];
  subtasks?: string[];
  endpointBehaviors?: string[];
  libraries?: string[];
  languages?: string[];
  licenses?: string[];
  formats?: string[];
}

const TASK_CATEGORY_KEY_GROUPS = [
  ['daimo:taskCategory', 'https://w3id.org/pionera/daimo#taskCategory', 'taskCategory']
];

const TASK_TYPE_KEYS = [
  'daimo:taskType',
  'https://w3id.org/pionera/daimo#taskType',
  'taskType'
];

const MODALITY_KEYS = [
  'daimo:modality',
  'https://w3id.org/pionera/daimo#modality',
  'modality'
];

const SUBTASK_KEYS = [
  'daimo:subtask',
  'https://w3id.org/pionera/daimo#subtask',
  'subtask'
];

const ENDPOINT_BEHAVIOR_KEYS = [
  'daimo:endpointBehavior',
  'https://w3id.org/pionera/daimo#endpointBehavior',
  'endpointBehavior'
];

const LIBRARY_KEYS = [
  'daimo:libraryName',
  'https://w3id.org/pionera/daimo#libraryName',
  'libraryName'
];

const LANGUAGE_KEYS = [
  'dct:language',
  'dcterms:language',
  'http://purl.org/dc/terms/language',
  'language'
];

const LICENSE_KEYS = [
  'dct:license',
  'dcterms:license',
  'http://purl.org/dc/terms/license',
  'license'
];

@Injectable({
  providedIn: 'root'
})
export class AiModelBrowserService {
  private readonly minPageSize = 200;
  private readonly currentParticipantId = `${environment.runtime.participantId || ''}`.trim().toLowerCase();

  constructor(
    private readonly assetService: AssetService,
    private readonly catalogBrowserService: CatalogBrowserService,
    private readonly contractDefinitionService: ContractDefinitionService
  ) {
  }

  getModels(filters: AiModelBrowserQuery = {}): Observable<AiModelBrowserItem[]> {
    return forkJoin({
      ownAssets: this.shouldLoadSource(filters, 'own') ? this.loadOwnAssets() : of([]),
      federatedOffers: this.shouldLoadSource(filters, 'federated') ? this.loadFederatedOffers(filters) : of([]),
      contractDefinitions: this.loadContractDefinitions()
    }).pipe(
      map(({ ownAssets, federatedOffers, contractDefinitions }) => {
        const ownContractAssetIds = this.extractContractRelatedAssetIds(contractDefinitions);
        const hasGlobalSelector = this.hasGlobalSelector(contractDefinitions);

        const ownModels = ownAssets
          .filter(asset => this.isMachineLearningAssetType(this.readLocalProperty(asset, [
            'assetType',
            'edc:assetType',
            'https://w3id.org/edc/v0.0.1/ns/assetType'
          ])))
          .map(asset => this.mapOwnAsset(asset, ownContractAssetIds, hasGlobalSelector));

        const federatedModels = federatedOffers
          .filter(offer => this.isMachineLearningAssetType(offer?.properties?.assetType))
          .filter(offer => !this.isCurrentConnectorOffer(offer))
          .filter(offer => this.hasAccessibleFederatedContract(offer))
          .map(offer => this.mapFederatedOffer(offer));

        return [...ownModels, ...federatedModels].sort((left, right) => {
          if (left.source !== right.source) {
            return left.source === 'own' ? -1 : 1;
          }

          return (left.name || left.id).localeCompare(right.name || right.id);
        });
      })
    );
  }

  private loadOwnAssets(): Observable<Asset[]> {
    return this.assetService.count().pipe(
      catchError(() => of(0)),
      switchMap(total => this.assetService.requestAssets(this.buildQuerySpec(total || this.minPageSize)).pipe(
        catchError(() => of([]))
      ))
    );
  }

  private loadFederatedOffers(filters: AiModelBrowserQuery): Observable<DataOffer[]> {
    return this.catalogBrowserService.count().pipe(
      catchError(() => of(0)),
      switchMap(total => this.catalogBrowserService.getPaginatedDataOffers(
        this.buildQuerySpec(total || this.minPageSize, this.buildFederatedFilterExpression(filters))
      ).pipe(
        catchError(() => of([]))
      ))
    );
  }

  private loadContractDefinitions(): Observable<ContractDefinition[]> {
    return this.contractDefinitionService.count().pipe(
      catchError(() => of(0)),
      switchMap(total => this.contractDefinitionService.queryAllContractDefinitions(this.buildQuerySpec(total || this.minPageSize)).pipe(
        catchError(() => of([]))
      ))
    );
  }

  private buildQuerySpec(total: number, filterExpression: any[] = []): QuerySpec {
    return {
      offset: 0,
      limit: Math.max(total, this.minPageSize),
      filterExpression
    };
  }

  private shouldLoadSource(filters: AiModelBrowserQuery, source: AiModelBrowserSource): boolean {
    return !filters.sources || filters.sources.length === 0 || filters.sources.includes(source);
  }

  private buildFederatedFilterExpression(filters: AiModelBrowserQuery): any[] {
    const filterExpression: any[] = [
      { operandLeft: 'daimo:assetType', operator: '=', operandRight: 'machineLearning' }
    ];

    const searchTerm = filters.searchTerm?.trim();
    if (searchTerm) {
      filterExpression.push({ operandLeft: 'daimo:search', operator: 'LIKE', operandRight: `%${searchTerm}%` });
    }

    this.addMultiValueFilter(filterExpression, 'daimo:taskCategory', filters.tasks);
    this.addMultiValueFilter(filterExpression, 'daimo:taskType', filters.taskTypes);
    this.addMultiValueFilter(filterExpression, 'daimo:modality', filters.modalities);
    this.addMultiValueFilter(filterExpression, 'daimo:subtask', filters.subtasks);
    this.addMultiValueFilter(filterExpression, 'daimo:endpointBehavior', filters.endpointBehaviors);
    this.addMultiValueFilter(filterExpression, 'daimo:libraryName', filters.libraries);
    this.addMultiValueFilter(filterExpression, 'daimo:language', filters.languages);
    this.addMultiValueFilter(filterExpression, 'daimo:license', filters.licenses);
    this.addMultiValueFilter(filterExpression, 'daimo:format', filters.formats);

    return filterExpression;
  }

  private addMultiValueFilter(filterExpression: any[], operandLeft: string, values?: string[]): void {
    const selected = this.unique(values || []);
    if (selected.length === 0) {
      return;
    }

    filterExpression.push({
      operandLeft,
      operator: '=',
      operandRight: selected.join(',')
    });
  }

  private mapOwnAsset(asset: Asset, ownContractAssetIds: Set<string>, hasGlobalSelector: boolean): AiModelBrowserItem {
    const id = `${(asset as any)?.id || (asset as any)?.['@id'] || ''}`;
    const version = this.firstText(this.readLocalProperty(asset, ['version'])) || 'N/A';
    const shortDescription = this.firstText(this.readLocalProperty(asset, ['shortDescription'])) || '';
    const description = this.firstText(this.readLocalProperty(asset, ['dcterms:description', 'dct:description', 'description', 'http://purl.org/dc/terms/description'])) || shortDescription;
    const assetData = this.normalizeAssetData(this.readLocalAssetData(asset));
    const properties = this.asRecord((asset as any)?.properties);
    const dataAddress = this.readLocalDataAddress(asset);
    const metadataNode = [assetData, properties, asset as unknown as Record<string, unknown>];

    return {
      id,
      name: this.firstText(this.readLocalProperty(asset, ['name'])) || id,
      version,
      description,
      shortDescription: shortDescription || description,
      keywords: this.extractTextList(this.readLocalProperty(asset, ['dcat:keyword', 'keywords', 'http://www.w3.org/ns/dcat#keyword'])),
      assetType: 'machineLearning',
      contentType: this.firstText(this.readLocalProperty(asset, ['contenttype'])) || 'Not available',
      format: this.firstText(this.readLocalProperty(asset, ['dcterms:format', 'dct:format', 'format', 'http://purl.org/dc/terms/format'])) || 'Unknown',
      storageType: this.normalizeStorageType(this.firstText(dataAddress['type'], dataAddress['@type']) || ''),
      fileName: this.firstText(dataAddress['keyName'], dataAddress['s3Key'], dataAddress['fileName'], dataAddress['filename']) || 'Unknown',
      tasks: this.collectPreferredMetadataValues(metadataNode, TASK_CATEGORY_KEY_GROUPS),
      taskTypes: this.collectMetadataValues(metadataNode, TASK_TYPE_KEYS),
      modalities: this.collectMetadataValues(metadataNode, MODALITY_KEYS),
      subtasks: this.collectMetadataValues(metadataNode, SUBTASK_KEYS),
      endpointBehaviors: this.collectMetadataValues(metadataNode, ENDPOINT_BEHAVIOR_KEYS),
      libraries: this.collectMetadataValues(metadataNode, LIBRARY_KEYS),
      languages: this.collectMetadataValues(metadataNode, LANGUAGE_KEYS),
      licenses: this.collectMetadataValues(metadataNode, LICENSE_KEYS),
      provider: environment.runtime.participantId || 'this-connector',
      source: 'own',
      hasContract: hasGlobalSelector || ownContractAssetIds.has(id),
      rawAsset: asset
    };
  }

  private mapFederatedOffer(offer: DataOffer): AiModelBrowserItem {
    const properties = this.asRecord(offer.properties);
    const assetData = this.normalizeAssetData(properties.assetData);
    const metadataNode = [assetData, properties, offer as unknown as Record<string, unknown>];

    return {
      id: `${offer.assetId}`,
      name: this.firstText(properties.name, properties.id) || offer.assetId,
      version: this.firstText(properties.version) || 'N/A',
      description: this.firstText(
        properties.description,
        properties['dct:description'],
        properties['dcterms:description'],
        properties['http://purl.org/dc/terms/description'],
        properties.shortDescription
      ) || '',
      shortDescription: this.firstText(properties.shortDescription, properties.description) || '',
      keywords: this.extractTextList([
        properties.keywords,
        properties['dcat:keyword'],
        properties['http://www.w3.org/ns/dcat#keyword']
      ]),
      assetType: 'machineLearning',
      contentType: this.firstText(properties.contenttype) || 'Not available',
      format: this.firstText(
        properties.format,
        properties['dct:format'],
        properties['dcterms:format'],
        properties['http://purl.org/dc/terms/format']
      ) || 'Unknown',
      storageType: this.normalizeStorageType(this.resolveOfferStorageType(properties)),
      fileName: this.firstText(properties.fileName) || 'Unknown',
      tasks: this.collectPreferredMetadataValues(metadataNode, TASK_CATEGORY_KEY_GROUPS),
      taskTypes: this.collectMetadataValues(metadataNode, TASK_TYPE_KEYS),
      modalities: this.collectMetadataValues(metadataNode, MODALITY_KEYS),
      subtasks: this.collectMetadataValues(metadataNode, SUBTASK_KEYS),
      endpointBehaviors: this.collectMetadataValues(metadataNode, ENDPOINT_BEHAVIOR_KEYS),
      libraries: this.collectMetadataValues(metadataNode, LIBRARY_KEYS),
      languages: this.collectMetadataValues(metadataNode, LANGUAGE_KEYS),
      licenses: this.collectMetadataValues(metadataNode, LICENSE_KEYS),
      provider: this.firstText(properties.participantId, offer.originator) || 'federated-provider',
      source: 'federated',
      hasContract: this.hasAccessibleFederatedContract(offer),
      rawOffer: offer
    };
  }

  private readLocalProperty(asset: Asset, keys: string[]): unknown {
    const properties = (asset as any)?.properties;
    if (!properties) {
      return undefined;
    }

    for (const key of keys) {
      if (typeof properties.optionalValue === 'function' && !key.includes(':') && !key.startsWith('http')) {
        const optionalValue = properties.optionalValue('edc', key);
        if (optionalValue !== undefined && optionalValue !== null && optionalValue !== '') {
          return optionalValue;
        }
      }

      const directValue = properties[key];
      if (directValue !== undefined && directValue !== null && directValue !== '') {
        return directValue;
      }
    }

    return undefined;
  }

  private readLocalAssetData(asset: Asset): unknown {
    const properties = (asset as any)?.properties;
    if (!properties) {
      return {};
    }

    const namespacedValue = properties['assetData']
      || properties['edc:assetData']
      || properties['https://w3id.org/edc/v0.0.1/ns/assetData'];

    if (typeof properties.optionalValue === 'function') {
      return properties.optionalValue('edc', 'assetData') || namespacedValue || {};
    }

    return namespacedValue || {};
  }

  private readLocalDataAddress(asset: Asset): Record<string, unknown> {
    const assetRecord = asset as any;
    const dataAddress = assetRecord?.['edc:dataAddress']
      || assetRecord?.['https://w3id.org/edc/v0.0.1/ns/dataAddress']
      || assetRecord?.dataAddress
      || assetRecord?.['dataAddress'];
    return this.asRecord(dataAddress);
  }

  private normalizeAssetData(assetData: unknown): Record<string, unknown> {
    if (typeof assetData === 'string') {
      try {
        return this.asRecord(JSON.parse(assetData));
      } catch {
        return {};
      }
    }

    return this.asRecord(assetData);
  }

  private collectMetadataValues(node: unknown, keys: string[]): string[] {
    const values: string[] = [];
    this.walkMetadata(node, new Set(keys), values);
    return this.unique(values);
  }

  private collectPreferredMetadataValues(node: unknown, keyGroups: string[][]): string[] {
    for (const keys of keyGroups) {
      const values = this.collectMetadataValues(node, keys);
      if (values.length > 0) {
        return values;
      }
    }

    return [];
  }

  private walkMetadata(node: unknown, keys: Set<string>, results: string[]): void {
    if (!node) {
      return;
    }

    if (Array.isArray(node)) {
      node.forEach(item => this.walkMetadata(item, keys, results));
      return;
    }

    if (typeof node !== 'object') {
      return;
    }

    const record = node as Record<string, unknown>;

    Object.entries(record).forEach(([key, value]) => {
      if (keys.has(key)) {
        results.push(...this.extractTextList(value));
      }

      this.walkMetadata(value, keys, results);
    });
  }

  private extractTextList(value: unknown): string[] {
    const values: string[] = [];
    this.collectTextValues(value, values);
    return this.unique(values);
  }

  private collectTextValues(value: unknown, results: string[]): void {
    if (value === undefined || value === null) {
      return;
    }

    if (Array.isArray(value)) {
      value.forEach(item => this.collectTextValues(item, results));
      return;
    }

    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      const normalized = `${value}`.trim();
      if (normalized.length > 0) {
        results.push(normalized);
      }
      return;
    }

    if (typeof value !== 'object') {
      return;
    }

    const record = value as Record<string, unknown>;

    if (record['@value'] !== undefined) {
      this.collectTextValues(record['@value'], results);
      return;
    }

    if (record['value'] !== undefined && Object.keys(record).length <= 2) {
      this.collectTextValues(record['value'], results);
      return;
    }

    Object.values(record).forEach(item => this.collectTextValues(item, results));
  }

  private firstText(...values: unknown[]): string {
    for (const value of values) {
      const texts = this.extractTextList(value);
      if (texts.length > 0) {
        return texts[0];
      }
    }

    return '';
  }

  private unique(values: string[]): string[] {
    return Array.from(new Set(values.map(value => value.trim()).filter(value => value.length > 0)));
  }

  private resolveOfferStorageType(properties: Record<string, unknown>): string {
    return this.firstText(
      properties.storageType,
      properties['edc:dataAddressType'],
      properties['https://w3id.org/edc/v0.0.1/ns/dataAddressType'],
      properties.type,
      properties['edc:type'],
      properties['https://w3id.org/edc/v0.0.1/ns/type']
    );
  }

  private normalizeStorageType(value: string): string {
    const normalized = value.trim();
    if (!normalized) {
      return 'Unknown';
    }

    const lower = normalized.toLowerCase();
    if (lower.includes('amazon') || lower.includes('s3')) {
      return 'S3';
    }

    if (lower.includes('http')) {
      return 'HttpData';
    }

    if (lower.includes('inesdatastore')) {
      return 'PIONERA Store';
    }

    return normalized;
  }

  private asRecord(value: unknown): Record<string, unknown> {
    if (!value || typeof value !== 'object') {
      return {};
    }

    return value as Record<string, unknown>;
  }

  private isMachineLearningAssetType(value: unknown): boolean {
    const normalized = this.firstText(value).trim().toLowerCase().replace(/[\s_-]/g, '');
    return normalized === 'machinelearning';
  }

  private hasOfferContracts(offer: DataOffer): boolean {
    const contractOffers = offer?.contractOffers as unknown;
    return Array.isArray(contractOffers) ? contractOffers.length > 0 : !!contractOffers;
  }

  private hasAccessibleFederatedContract(offer: DataOffer): boolean {
    return this.hasOfferContracts(offer) && this.firstText(offer?.endpointUrl).length > 0;
  }

  private isCurrentConnectorOffer(offer: DataOffer): boolean {
    const participantId = `${offer?.properties?.participantId || offer?.originator || ''}`.trim().toLowerCase();
    return participantId.length > 0 && participantId === this.currentParticipantId;
  }

  private extractContractRelatedAssetIds(contractDefinitions: ContractDefinition[]): Set<string> {
    const assetIds = new Set<string>();

    for (const definition of contractDefinitions) {
      const selectors = this.getDefinitionSelectors(definition);
      for (const selector of selectors) {
        const ids = this.getSelectorOperandRightValues(selector);
        ids.forEach(id => assetIds.add(id));
      }
    }

    return assetIds;
  }

  private hasGlobalSelector(contractDefinitions: ContractDefinition[]): boolean {
    return contractDefinitions.some(definition => this.getDefinitionSelectors(definition).length === 0);
  }

  private getDefinitionSelectors(definition: ContractDefinition): any[] {
    const selectorKey = 'https://w3id.org/edc/v0.0.1/ns/assetsSelector';
    const selectors = (definition as any)?.assetsSelector || (definition as any)?.[selectorKey] || [];
    return Array.isArray(selectors) ? selectors : selectors ? [selectors] : [];
  }

  private getSelectorOperandRightValues(selector: any): string[] {
    const operandRightKey = 'https://w3id.org/edc/v0.0.1/ns/operandRight';
    const operandRight = selector?.operandRight || selector?.[operandRightKey] || [];
    const values = Array.isArray(operandRight) ? operandRight : [operandRight];

    return values
      .map(value => value?.['@value'] || value?.value || value)
      .filter(value => value !== undefined && value !== null && `${value}`.trim().length > 0)
      .map(value => `${value}`.trim());
  }
}
