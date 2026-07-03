import { HttpClient, HttpResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { forkJoin, Observable, of, throwError } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { environment } from 'src/environments/environment';
import { AiModelBenchmarkModelType, AiModelExecutionInputFeature, AiModelExecutionItem, AiModelRequestShape, ModelExecutionRequestPayload, ModelExecutionResponsePayload } from '../models/ai-model-execution-item';
import { Asset, QuerySpec } from '../models/edc-connector-entities';
import { DataOffer } from '../models/data-offer';
import { AssetService } from './asset.service';
import { CatalogBrowserService } from './catalog-browser.service';
import { ContractAgreementService } from './contractAgreement.service';

@Injectable({
  providedIn: 'root'
})
export class ModelExecutionService {
  private readonly minPageSize = 200;
  private readonly currentParticipantId = `${environment.runtime.participantId || ''}`.trim().toLowerCase();
  private readonly executeUrl = `${environment.runtime.managementApiUrl}${environment.runtime.service.modelExecution.baseUrl}${environment.runtime.service.modelExecution.execute}`;

  constructor(
    private readonly http: HttpClient,
    private readonly assetService: AssetService,
    private readonly catalogBrowserService: CatalogBrowserService,
    private readonly contractAgreementService: ContractAgreementService
  ) {
  }

  getExecutableModels(): Observable<AiModelExecutionItem[]> {
    return this.loadHttpModels(true);
  }

  getBenchmarkModels(): Observable<AiModelExecutionItem[]> {
    return this.loadHttpModels(false);
  }

  private loadHttpModels(requireAgreementForFederated: boolean): Observable<AiModelExecutionItem[]> {
    return forkJoin({
      ownAssets: this.loadOwnAssets(),
      federatedOffers: this.loadFederatedOffers(),
      agreementAssetIds: this.loadAgreementAssetIds()
    }).pipe(
      map(({ ownAssets, federatedOffers, agreementAssetIds }) => {
        const ownModels = ownAssets
          .filter(asset => this.isMachineLearningAsset(this.readLocalProperty(asset, ['assetType', 'edc:assetType', 'https://w3id.org/edc/v0.0.1/ns/assetType'])))
          .filter(asset => this.isLocalHttpAsset(asset))
          .map(asset => this.mapOwnAsset(asset));

        const federatedModels = federatedOffers
          .filter(offer => this.isMachineLearningAsset(offer?.properties?.assetType))
          .filter(offer => !this.isCurrentConnectorOffer(offer))
          .filter(offer => this.isFederatedHttpAsset(offer))
          .filter(offer => !requireAgreementForFederated || agreementAssetIds.has(`${offer.assetId}`))
          .map(offer => this.mapFederatedOffer(offer, agreementAssetIds.has(`${offer.assetId}`)));

        return [...ownModels, ...federatedModels].sort((left, right) => {
          if (left.source !== right.source) {
            return left.source === 'own' ? -1 : 1;
          }
          return left.name.localeCompare(right.name);
        });
      })
    );
  }

  executeModel(request: ModelExecutionRequestPayload): Observable<ModelExecutionResponsePayload> {
    return this.http.post(this.executeUrl, request, {
      observe: 'response',
      responseType: 'text'
    }).pipe(
      map(response => this.mapExecutionResponse(response)),
      catchError(error => {
        return throwError(() => error);
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

  private loadFederatedOffers(): Observable<DataOffer[]> {
    return this.catalogBrowserService.count().pipe(
      catchError(() => of(0)),
      switchMap(total => this.catalogBrowserService.getPaginatedDataOffers(
        this.buildQuerySpec(total || this.minPageSize, [
          { operandLeft: 'daimo:assetType', operator: '=', operandRight: 'machineLearning' }
        ])
      ).pipe(
        catchError(() => of([]))
      ))
    );
  }

  private loadAgreementAssetIds(): Observable<Set<string>> {
    return this.contractAgreementService.count().pipe(
      catchError(() => of(0)),
      switchMap(total => this.contractAgreementService.queryAllAgreements(this.buildQuerySpec(total || this.minPageSize)).pipe(
        map(results => this.extractAgreementAssetIds(results || [])),
        catchError(() => of(new Set<string>()))
      ))
    );
  }

  private mapExecutionResponse(response: HttpResponse<string>): ModelExecutionResponsePayload {
    const body = response.body || '';
    const contentType = response.headers.get('content-type') || 'application/json';
    return {
      statusCode: response.status,
      contentType,
      body,
      parsedBody: this.parseJsonLikeValue(body)
    };
  }

  private buildQuerySpec(total: number, filterExpression: any[] = []): QuerySpec {
    return {
      offset: 0,
      limit: Math.max(total, this.minPageSize),
      filterExpression
    };
  }

  private mapOwnAsset(asset: Asset): AiModelExecutionItem {
    const assetData = this.normalizeAssetData(this.readLocalAssetData(asset));
    const properties = this.asRecord((asset as any)?.properties);
    const dataAddress = this.readLocalDataAddress(asset);
    const metadataNode = [assetData, properties, asset as unknown as Record<string, unknown>];
    const inputSchema = this.extractInputSchema(metadataNode);
    const requestShape = this.extractRequestShape(metadataNode, inputSchema);
    return {
      id: `${(asset as any)?.id || (asset as any)?.['@id'] || ''}`,
      name: this.firstText(this.readLocalProperty(asset, ['name'])) || `${(asset as any)?.id || ''}`,
      provider: environment.runtime.participantId || 'this-connector',
      source: 'own',
      isLocal: true,
      hasAgreement: true,
      contentType: this.firstText(this.readLocalProperty(asset, ['contenttype'])) || 'Not available',
      description: this.firstText(
        this.readLocalProperty(asset, ['dcterms:description', 'description', 'http://purl.org/dc/terms/description']),
        this.readLocalProperty(asset, ['shortDescription'])
      ),
      executionPath: this.firstText(dataAddress['path'], dataAddress['edc:path'], dataAddress['proxyPath'], dataAddress['edc:proxyPath']) || '',
      httpMethodDefault: this.firstText(dataAddress['method'], dataAddress['edc:method']) || 'POST',
      tasks: this.collectPreferredMetadataValues(metadataNode, [
        ['daimo:taskCategory', 'https://w3id.org/pionera/daimo#taskCategory', 'taskCategory']
      ]),
      taskTypes: this.collectMetadataValues(metadataNode, ['daimo:taskType', 'https://w3id.org/pionera/daimo#taskType', 'taskType']),
      modalities: this.collectMetadataValues(metadataNode, ['daimo:modality', 'https://w3id.org/pionera/daimo#modality', 'modality']),
      subtasks: this.collectMetadataValues(metadataNode, ['daimo:subtask', 'https://w3id.org/pionera/daimo#subtask', 'subtask']),
      endpointBehaviors: this.collectMetadataValues(metadataNode, ['daimo:endpointBehavior', 'https://w3id.org/pionera/daimo#endpointBehavior', 'endpointBehavior']),
      libraries: this.collectMetadataValues(metadataNode, ['daimo:libraryName', 'https://w3id.org/pionera/daimo#libraryName', 'libraryName']),
      algorithms: [],
      frameworks: [],
      inputFeatures: this.extractInputFeatures(metadataNode, inputSchema),
      inputColumns: this.extractInputColumns(metadataNode),
      inputSchema,
      inputExample: this.extractInputExample(metadataNode),
      requestShape,
      benchmarkModelType: this.extractBenchmarkModelType(metadataNode),
      supportedMetrics: this.extractSupportedMetrics(metadataNode),
      predictionFields: this.extractPredictionFields(metadataNode),
      positiveLabel: this.extractPositiveLabel(metadataNode),
      scoreField: this.extractScoreField(metadataNode),
      rawAsset: asset
    };
  }

  private mapFederatedOffer(offer: DataOffer, hasAgreement: boolean): AiModelExecutionItem {
    const properties = this.asRecord(offer?.properties);
    const assetData = this.normalizeAssetData(properties.assetData);
    const metadataNode = [assetData, properties, offer as unknown as Record<string, unknown>];
    const inputSchema = this.extractInputSchema(metadataNode);
    const requestShape = this.extractRequestShape(metadataNode, inputSchema);
    return {
      id: `${offer.assetId}`,
      name: this.firstText(offer?.properties?.name, offer.assetId) || `${offer.assetId}`,
      provider: this.firstText(offer?.properties?.participantId, offer.originator) || 'federated-provider',
      source: 'federated',
      isLocal: false,
      hasAgreement,
      contentType: this.firstText(offer?.properties?.contenttype) || 'Not available',
      description: this.firstText(offer?.properties?.description, offer?.properties?.shortDescription),
      executionPath: this.firstText(offer?.properties?.path) || '',
      httpMethodDefault: this.firstText(offer?.properties?.method) || 'POST',
      tasks: this.collectPreferredMetadataValues(metadataNode, [
        ['daimo:taskCategory', 'https://w3id.org/pionera/daimo#taskCategory', 'taskCategory']
      ]),
      taskTypes: this.collectMetadataValues(metadataNode, ['daimo:taskType', 'https://w3id.org/pionera/daimo#taskType', 'taskType']),
      modalities: this.collectMetadataValues(metadataNode, ['daimo:modality', 'https://w3id.org/pionera/daimo#modality', 'modality']),
      subtasks: this.collectMetadataValues(metadataNode, ['daimo:subtask', 'https://w3id.org/pionera/daimo#subtask', 'subtask']),
      endpointBehaviors: this.collectMetadataValues(metadataNode, ['daimo:endpointBehavior', 'https://w3id.org/pionera/daimo#endpointBehavior', 'endpointBehavior']),
      libraries: this.collectMetadataValues(metadataNode, ['daimo:libraryName', 'https://w3id.org/pionera/daimo#libraryName', 'libraryName']),
      algorithms: [],
      frameworks: [],
      inputFeatures: this.extractInputFeatures(metadataNode, inputSchema),
      inputColumns: this.extractInputColumns(metadataNode),
      inputSchema,
      inputExample: this.extractInputExample(metadataNode),
      requestShape,
      benchmarkModelType: this.extractBenchmarkModelType(metadataNode),
      supportedMetrics: this.extractSupportedMetrics(metadataNode),
      predictionFields: this.extractPredictionFields(metadataNode),
      positiveLabel: this.extractPositiveLabel(metadataNode),
      scoreField: this.extractScoreField(metadataNode),
      rawOffer: offer
    };
  }

  private extractAgreementAssetIds(agreements: any[]): Set<string> {
    const assetIds = new Set<string>();
    agreements.forEach(agreement => {
      const resolvedAssetId = this.firstText(
        agreement?.assetId,
        agreement?.['edc:assetId'],
        agreement?.['https://w3id.org/edc/v0.0.1/ns/assetId'],
        agreement?.asset?.['@id'],
        agreement?.asset?.id,
        agreement?.asset?.assetId,
        agreement?.asset,
        agreement?.['edc:asset']?.['@id'],
        agreement?.['edc:asset']?.id,
        agreement?.['edc:asset']
      );
      if (resolvedAssetId) {
        assetIds.add(resolvedAssetId);
      }
    });
    return assetIds;
  }

  private isLocalHttpAsset(asset: Asset): boolean {
    const storageType = this.resolveLocalStorageType(asset).toLowerCase();
    return storageType.includes('http');
  }

  private isFederatedHttpAsset(offer: DataOffer): boolean {
    const storageType = this.resolveOfferStorageType(this.asRecord(offer?.properties)).toLowerCase();
    return storageType.includes('http');
  }

  private isCurrentConnectorOffer(offer: DataOffer): boolean {
    const participantId = `${offer?.properties?.participantId || offer?.originator || ''}`.trim().toLowerCase();
    return participantId.length > 0 && participantId === this.currentParticipantId;
  }

  private isMachineLearningAsset(value: unknown): boolean {
    const normalized = this.firstText(value).trim().toLowerCase().replace(/[\s_-]/g, '');
    return normalized === 'machinelearning';
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
    const dataAddress = this.resolveLocalDataAddressValue(assetRecord);
    const normalized = this.asRecord(dataAddress);

    for (const key of ['type', 'path', 'proxyPath', 'method']) {
      const namespacedKey = `https://w3id.org/edc/v0.0.1/ns/${key}`;
      const directValue = normalized[key]
        ?? normalized[`edc:${key}`]
        ?? normalized[namespacedKey];

      if (directValue !== undefined && directValue !== null && directValue !== '') {
        normalized[key] = directValue;
        continue;
      }

      if (typeof (dataAddress as any)?.optionalValue === 'function') {
        const optionalValue = (dataAddress as any).optionalValue('edc', key);
        if (optionalValue !== undefined && optionalValue !== null && optionalValue !== '') {
          normalized[key] = optionalValue;
        }
      }
    }

    if (!this.firstText(normalized['type'], normalized['@type'], normalized['edc:type'])) {
      const resolvedStorageType = this.resolveLocalStorageType(asset);
      if (resolvedStorageType) {
        normalized['type'] = resolvedStorageType;
      }
    }

    return normalized;
  }

  private resolveLocalStorageType(asset: Asset): string {
    const dataAddress = this.readLocalDataAddressFromRecord(asset);
    return this.firstText(
      dataAddress['type'],
      dataAddress['@type'],
      dataAddress['edc:type'],
      this.readLocalProperty(asset, [
        'dataAddressType',
        'edc:dataAddressType',
        'https://w3id.org/edc/v0.0.1/ns/dataAddressType'
      ])
    );
  }

  private resolveOfferStorageType(properties: Record<string, unknown>): string {
    return this.firstText(
      properties['storageType'],
      properties['edc:dataAddressType'],
      properties['https://w3id.org/edc/v0.0.1/ns/dataAddressType'],
      properties['type'],
      properties['edc:type'],
      properties['https://w3id.org/edc/v0.0.1/ns/type']
    );
  }

  private readLocalDataAddressFromRecord(asset: Asset): Record<string, unknown> {
    const assetRecord = asset as any;
    return this.asRecord(this.resolveLocalDataAddressValue(assetRecord));
  }

  private resolveLocalDataAddressValue(assetRecord: any): unknown {
    return this.parseJsonLikeValue(
      assetRecord?.dataAddress
      || assetRecord?.['dataAddress']
      || assetRecord?.['edc:dataAddress']
      || assetRecord?.['https://w3id.org/edc/v0.0.1/ns/dataAddress']
    );
  }

  private normalizeAssetData(assetData: unknown): unknown {
    return this.parseJsonLikeValue(assetData);
  }

  private extractInputSchema(node: unknown): unknown {
    const value = this.findFirstValue(node, [
      'daimo:inputSchema',
      'https://w3id.org/pionera/daimo#inputSchema',
      'inputSchema'
    ]);

    if (value !== undefined) {
      return this.parseJsonLikeValue(value);
    }

    return undefined;
  }

  private extractInputFeatures(node: unknown, inputSchema: unknown): AiModelExecutionInputFeature[] {
    const schemaFeatures = this.parseInputFeatureCollection(inputSchema);
    if (schemaFeatures.length > 0) {
      return schemaFeatures;
    }

    const jsonSchemaFeatures = this.buildInputFeaturesFromSchema(inputSchema);
    if (jsonSchemaFeatures.length > 0) {
      return jsonSchemaFeatures;
    }

    return [];
  }

  private extractInputColumns(node: unknown): string[] {
    return this.extractFieldNameList(node, [
      'daimo:input',
      'https://w3id.org/pionera/daimo#input',
      'input'
    ]);
  }

  private extractInputExample(node: unknown): unknown {
    const value = this.findFirstValue(node, [
      'daimo:inputExample',
      'https://w3id.org/pionera/daimo#inputExample',
      'inputExample'
    ]);
    return this.parseJsonLikeValue(value);
  }

  private extractRequestShape(node: unknown, inputSchema: unknown): AiModelRequestShape {
    const raw = this.findFirstValue(node, [
      'daimo:requestShape',
      'https://w3id.org/pionera/daimo#requestShape',
      'requestShape'
    ]);

    const parsed = this.parseJsonLikeValue(raw);
    if (typeof parsed === 'boolean') {
      return parsed ? 'batch' : 'single';
    }

    const shape = this.firstText(parsed).toLowerCase();
    if (['batch', 'array', 'list', 'records', 'rows'].includes(shape)) {
      return 'batch';
    }
    if (['single', 'object', 'record', 'row'].includes(shape)) {
      return 'single';
    }

    return this.isArraySchema(inputSchema) ? 'batch' : 'single';
  }

  private extractBenchmarkModelType(node: unknown): AiModelBenchmarkModelType {
    const raw = this.findFirstValue(node, [
      'daimo:endpointBehavior',
      'https://w3id.org/pionera/daimo#endpointBehavior',
      'endpointBehavior'
    ]);
    const value = this.firstText(this.parseJsonLikeValue(raw)).toLowerCase().replace(/[\s_-]/g, '');

    return ['metric', 'metrics', 'evaluator', 'evaluation'].includes(value) ? 'metric' : 'output';
  }

  private extractSupportedMetrics(node: unknown): string[] {
    const directMetrics = this.collectMetricNames(this.findFirstValue(node, [
      'daimo:metrics',
      'https://w3id.org/pionera/daimo#metrics',
      'daimo:metric',
      'https://w3id.org/pionera/daimo#metric',
      'http://data.europa.eu/it6/hasEvaluationMeasure',
      'metrics',
      'metric'
    ]));
    const evaluationMetrics = this.collectMetricNames(this.findFirstValue(node, [
      'ModelEvaluation',
      'modelEvaluation',
      'evaluations'
    ]));

    return this.unique([...directMetrics, ...evaluationMetrics]);
  }

  private extractPredictionFields(node: unknown): string[] {
    return this.extractFieldNameList(node, [
      'daimo:prediction',
      'https://w3id.org/pionera/daimo#prediction',
      'prediction',
      'daimo:predictionField',
      'https://w3id.org/pionera/daimo#predictionField',
      'predictionField',
      'daimo:predictionFields',
      'https://w3id.org/pionera/daimo#predictionFields',
      'predictionFields',
      'daimo:prediction_field',
      'https://w3id.org/daimo/ns#prediction_field',
      'https://pionera.ai/edc/daimo#prediction_field',
      'prediction_field',
      'daimo:prediction_fields',
      'https://w3id.org/daimo/ns#prediction_fields',
      'https://pionera.ai/edc/daimo#prediction_fields',
      'prediction_fields'
    ]);
  }

  private extractPositiveLabel(node: unknown): string {
    return this.firstText(this.findFirstValue(node, [
      'daimo:positiveLabel',
      'https://w3id.org/pionera/daimo#positiveLabel',
      'positiveLabel',
      'positiveClass'
    ]));
  }

  private extractScoreField(node: unknown): string {
    return this.firstText(this.findFirstValue(node, [
      'daimo:scoreField',
      'https://w3id.org/pionera/daimo#scoreField',
      'scoreField',
      'confidenceField',
      'probabilityField'
    ]));
  }

  private extractFieldNameList(node: unknown, keys: string[]): string[] {
    const raw = this.findFirstValue(node, keys);
    return this.unique(this.collectFieldNames(this.parseJsonLikeValue(raw)));
  }

  private collectMetricNames(value: unknown): string[] {
    const parsed = this.parseJsonLikeValue(value);
    if (parsed === undefined || parsed === null) {
      return [];
    }

    if (Array.isArray(parsed)) {
      return parsed.reduce<string[]>((metrics, item) => {
        metrics.push(...this.collectMetricNames(item));
        return metrics;
      }, []);
    }

    if (typeof parsed === 'string') {
      return parsed
        .split(',')
        .map(item => item.trim())
        .filter(item => item.length > 0);
    }

    if (!this.isRecord(parsed)) {
      return [];
    }

    const directName = this.firstText(parsed['metric'], parsed['name'], parsed['key'], parsed['id']);
    if (directName) {
      return [directName];
    }

    for (const key of ['metrics', 'metric', 'items', 'values', 'evaluations', 'ModelEvaluation', 'modelEvaluation']) {
      if (parsed[key] !== undefined) {
        return this.collectMetricNames(parsed[key]);
      }
    }

    return [];
  }

  private collectFieldNames(value: unknown): string[] {
    const parsed = this.parseJsonLikeValue(value);
    if (parsed === undefined || parsed === null) {
      return [];
    }

    if (Array.isArray(parsed)) {
      return parsed.reduce<string[]>((fields, item) => {
        fields.push(...this.collectFieldNames(item));
        return fields;
      }, []);
    }

    if (typeof parsed === 'string') {
      return parsed
        .split(',')
        .map(item => item.trim())
        .filter(item => item.length > 0);
    }

    if (typeof parsed === 'number' || typeof parsed === 'boolean') {
      return [`${parsed}`];
    }

    if (!this.isRecord(parsed)) {
      return [];
    }

    const directName = this.firstText(parsed['name'], parsed['field'], parsed['path'], parsed['id']);
    if (directName) {
      return [directName];
    }

    for (const key of ['fields', 'features', 'targets', 'predictions', 'outputs']) {
      if (Array.isArray(parsed[key])) {
        return this.collectFieldNames(parsed[key]);
      }
    }

    return [];
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

  private findFirstValue(node: unknown, keys: string[]): unknown {
    if (node === undefined || node === null) {
      return undefined;
    }

    const parsed = this.parseJsonLikeValue(node);
    if (Array.isArray(parsed)) {
      for (const item of parsed) {
        const nested = this.findFirstValue(item, keys);
        if (nested !== undefined) {
          return nested;
        }
      }
      return undefined;
    }

    if (!this.isRecord(parsed)) {
      return undefined;
    }

    for (const [key, value] of Object.entries(parsed)) {
      if (keys.includes(key)) {
        return value;
      }

      const nested = this.findFirstValue(value, keys);
      if (nested !== undefined) {
        return nested;
      }
    }

    return undefined;
  }

  private parseJsonLikeValue(value: unknown): unknown {
    if (value === undefined || value === null) {
      return undefined;
    }

    // Unwrap JSON-LD @value wrapper objects (EDC may wrap metadata values)
    if (typeof value === 'object' && !Array.isArray(value)) {
      const record = value as Record<string, unknown>;
      if (record['@value'] !== undefined) {
        return this.parseJsonLikeValue(record['@value']);
      }
      if (record['@list'] !== undefined) {
        return this.parseJsonLikeValue(record['@list']);
      }
      if (record['value'] !== undefined && Object.keys(record).length <= 2) {
        return this.parseJsonLikeValue(record['value']);
      }
    }

    // Unwrap arrays of @value wrapper objects (single-element wrappers)
    if (Array.isArray(value) && value.length === 1 && value[0] && typeof value[0] === 'object' && value[0]['@value'] !== undefined) {
      return this.parseJsonLikeValue(value[0]['@value']);
    }

    if (typeof value !== 'string') {
      return value;
    }

    const trimmed = value.trim();
    if (!trimmed) {
      return undefined;
    }

    if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
      try {
        return JSON.parse(trimmed);
      } catch {
        return value;
      }
    }

    return value;
  }

  private parseInputFeatureCollection(value: unknown): AiModelExecutionInputFeature[] {
    const parsed = this.unwrapInputSchemaContainer(this.parseJsonLikeValue(value));
    const schemaRecord = this.asRecord(parsed);
    const fieldCollection = this.parseJsonLikeValue(this.readAliasedValue(schemaRecord, [
      'fields',
      'features',
      'inputFields',
      'https://w3id.org/edc/v0.0.1/ns/fields',
      'https://w3id.org/edc/v0.0.1/ns/features',
      'https://w3id.org/edc/v0.0.1/ns/inputFields',
      'https://w3id.org/pionera/daimo#fields',
      'https://w3id.org/pionera/daimo#inputFields'
    ]));
    const rawFields = Array.isArray(parsed)
      ? parsed
      : Array.isArray(fieldCollection)
        ? fieldCollection
        : schemaRecord.text !== undefined
          ? [{
            name: 'text',
            type: this.firstText(schemaRecord.type) || 'string',
            required: true,
            description: this.firstText(schemaRecord.description) || 'Text to analyze'
          }]
          : [];

    if (!Array.isArray(rawFields)) {
      return [];
    }

    return rawFields
      .map(item => this.parseJsonLikeValue(item))
      .map(item => typeof item === 'string' ? { name: item, type: 'string', required: false } : this.asRecord(item))
      .filter(item => !!this.getInputFieldName(item))
      .map(item => ({
        name: this.getInputFieldName(item),
        type: this.getInputFieldType(item),
        required: this.getInputFieldRequired(item),
        description: this.getInputFieldDescription(item),
        minValue: this.getInputFieldMinValue(item),
        maxValue: this.getInputFieldMaxValue(item)
      }));
  }

  private buildInputFeaturesFromSchema(schema: unknown): AiModelExecutionInputFeature[] {
    const schemaRecord = this.resolveSchemaRoot(this.asRecord(this.resolveInputJsonSchema(schema)));
    if (!this.isRecord(schemaRecord)) {
      return [];
    }

    const features: AiModelExecutionInputFeature[] = [];
    this.collectSchemaFeatures(schemaRecord, '', new Set<string>(), features);
    return features;
  }

  private collectSchemaFeatures(
    schemaNode: Record<string, unknown>,
    prefix: string,
    requiredByParent: Set<string>,
    target: AiModelExecutionInputFeature[]
  ): void {
    const propertiesNode = schemaNode['properties'];
    if (!this.isRecord(propertiesNode)) {
      return;
    }

    const requiredSet = new Set<string>([
      ...requiredByParent,
      ...this.readRequiredFields(schemaNode['required'])
    ]);

    Object.entries(propertiesNode).forEach(([propertyName, propertySchema]) => {
      const schemaRecord = this.asRecord(this.parseJsonLikeValue(propertySchema));
      const path = prefix ? `${prefix}.${propertyName}` : propertyName;
      const inferredType = this.inferSchemaType(schemaRecord);

      if (inferredType === 'object' && this.isRecord(schemaRecord['properties'])) {
        this.collectSchemaFeatures(schemaRecord, path, new Set<string>(), target);
        return;
      }

      if (inferredType === 'array' && this.isRecord(schemaRecord['items'])) {
        const itemSchema = this.asRecord(schemaRecord['items']);
        if (this.isRecord(itemSchema['properties'])) {
          this.collectSchemaFeatures(itemSchema, `${path}[]`, new Set<string>(), target);
          return;
        }
      }

      target.push({
        name: path,
        type: inferredType,
        required: requiredSet.has(propertyName),
        description: this.firstText(schemaRecord.description, schemaRecord.title) || undefined,
        minValue: this.getInputFieldMinValue(schemaRecord),
        maxValue: this.getInputFieldMaxValue(schemaRecord)
      });
    });
  }

  private resolveSchemaRoot(schemaNode: Record<string, unknown>): Record<string, unknown> {
    if (this.isArraySchema(schemaNode)) {
      const itemSchema = this.asRecord(schemaNode['items']);
      if (this.isRecord(itemSchema)) {
        return itemSchema;
      }
    }

    const nestedKeys = ['input', 'payload', 'body', 'requestBody'];
    for (const key of nestedKeys) {
      const nested = this.asRecord(schemaNode[key]);
      if (this.isArraySchema(nested)) {
        const itemSchema = this.asRecord(nested['items']);
        if (this.isRecord(itemSchema)) {
          return itemSchema;
        }
      }
      if (this.isRecord(nested['properties']) || Array.isArray(nested['required'])) {
        return nested;
      }
    }

    return schemaNode;
  }

  private unwrapInputSchemaContainer(value: unknown): unknown {
    if (!Array.isArray(value) || value.length !== 1 || !this.isRecord(value[0])) {
      return value;
    }

    const record = value[0] as Record<string, unknown>;
    const hasInputSchemaShape = this.readAliasedValue(record, [
      'fields',
      'features',
      'inputFields',
      'jsonSchema',
      'schema',
      'https://w3id.org/edc/v0.0.1/ns/fields',
      'https://w3id.org/edc/v0.0.1/ns/features',
      'https://w3id.org/edc/v0.0.1/ns/inputFields',
      'https://w3id.org/edc/v0.0.1/ns/jsonSchema',
      'https://w3id.org/pionera/daimo#fields',
      'https://w3id.org/pionera/daimo#inputFields',
      'https://w3id.org/pionera/daimo#jsonSchema'
    ]) !== undefined;

    return hasInputSchemaShape ? record : value;
  }

  private resolveInputJsonSchema(schema: unknown): unknown {
    const parsed = this.unwrapInputSchemaContainer(this.parseJsonLikeValue(schema));
    const schemaRecord = this.asRecord(parsed);
    const jsonSchema = this.parseJsonLikeValue(this.readAliasedValue(schemaRecord, [
      'jsonSchema',
      'schema',
      'https://w3id.org/edc/v0.0.1/ns/jsonSchema',
      'https://w3id.org/edc/v0.0.1/ns/schema',
      'https://w3id.org/pionera/daimo#jsonSchema'
    ]));

    return jsonSchema !== undefined ? jsonSchema : parsed;
  }

  private getInputFieldName(item: Record<string, unknown>): string {
    return this.firstText(
      item.name,
      item.field,
      item.path,
      item['https://w3id.org/edc/v0.0.1/ns/name'],
      item['https://w3id.org/edc/v0.0.1/ns/field'],
      item['https://w3id.org/edc/v0.0.1/ns/path'],
      item['https://w3id.org/pionera/daimo#name'],
      item['https://w3id.org/pionera/daimo#field']
    );
  }

  private getInputFieldType(item: Record<string, unknown>): string {
    return this.firstText(
      item.type,
      item.dataType,
      item.dtype,
      item['https://w3id.org/edc/v0.0.1/ns/type'],
      item['https://w3id.org/edc/v0.0.1/ns/dataType'],
      item['https://w3id.org/pionera/daimo#type'],
      item['https://w3id.org/pionera/daimo#dataType']
    ) || 'string';
  }

  private getInputFieldRequired(item: Record<string, unknown>): boolean {
    const required = this.readAliasedValue(item, [
      'required',
      'https://w3id.org/edc/v0.0.1/ns/required',
      'https://w3id.org/pionera/daimo#required'
    ]);
    if (required !== undefined) {
      return this.readBoolean(required);
    }

    const nullable = this.readAliasedValue(item, [
      'nullable',
      'https://w3id.org/edc/v0.0.1/ns/nullable',
      'https://w3id.org/pionera/daimo#nullable'
    ]);
    return !this.readBoolean(nullable);
  }

  private getInputFieldDescription(item: Record<string, unknown>): string | undefined {
    return this.firstText(
      item.description,
      item.title,
      item['https://w3id.org/edc/v0.0.1/ns/description'],
      item['https://w3id.org/edc/v0.0.1/ns/title'],
      item['http://purl.org/dc/terms/description'],
      item['http://purl.org/dc/terms/title'],
      item['https://w3id.org/pionera/daimo#description']
    ) || undefined;
  }

  private getInputFieldMinValue(item: Record<string, unknown>): number | undefined {
    return this.readNumber(this.readAliasedValue(item, [
      'minValue',
      'min',
      'minimum',
      'https://w3id.org/edc/v0.0.1/ns/minValue',
      'https://w3id.org/edc/v0.0.1/ns/min',
      'https://w3id.org/edc/v0.0.1/ns/minimum',
      'https://w3id.org/pionera/daimo#minValue',
      'https://w3id.org/pionera/daimo#min',
      'https://w3id.org/pionera/daimo#minimum'
    ]));
  }

  private getInputFieldMaxValue(item: Record<string, unknown>): number | undefined {
    return this.readNumber(this.readAliasedValue(item, [
      'maxValue',
      'max',
      'maximum',
      'https://w3id.org/edc/v0.0.1/ns/maxValue',
      'https://w3id.org/edc/v0.0.1/ns/max',
      'https://w3id.org/edc/v0.0.1/ns/maximum',
      'https://w3id.org/pionera/daimo#maxValue',
      'https://w3id.org/pionera/daimo#max',
      'https://w3id.org/pionera/daimo#maximum'
    ]));
  }

  private readAliasedValue(record: Record<string, unknown>, keys: string[]): unknown {
    for (const key of keys) {
      if (record[key] !== undefined) {
        return record[key];
      }
    }
    return undefined;
  }

  private isArraySchema(schema: unknown): boolean {
    const schemaNode = this.asRecord(this.resolveInputJsonSchema(schema));
    if (!this.isRecord(schemaNode)) {
      return false;
    }

    const typeNode = schemaNode['type'];
    if (typeof typeNode === 'string' && typeNode.trim().toLowerCase() === 'array') {
      return true;
    }

    return Array.isArray(typeNode)
      && typeNode.some(item => typeof item === 'string' && item.trim().toLowerCase() === 'array');
  }

  private inferSchemaType(schemaNode: Record<string, unknown>): string {
    const typeNode = schemaNode['type'];
    if (typeof typeNode === 'string' && typeNode.trim().length > 0) {
      return typeNode.trim().toLowerCase();
    }

    if (Array.isArray(typeNode)) {
      const first = typeNode.find(item => typeof item === 'string' && item.trim().length > 0);
      if (typeof first === 'string') {
        return first.trim().toLowerCase();
      }
    }

    if (Array.isArray(schemaNode['enum'])) {
      return 'string';
    }

    if (this.isRecord(schemaNode['properties'])) {
      return 'object';
    }

    if (this.isRecord(schemaNode['items'])) {
      return 'array';
    }

    return 'string';
  }

  private readRequiredFields(value: unknown): string[] {
    if (!Array.isArray(value)) {
      return [];
    }

    return value
      .filter(field => typeof field === 'string' && field.trim().length > 0)
      .map(field => `${field}`.trim());
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
      if (normalized) {
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

  private readBoolean(value: unknown): boolean {
    const parsed = this.parseJsonLikeValue(value);
    if (parsed !== value) {
      return this.readBoolean(parsed);
    }

    if (typeof value === 'boolean') {
      return value;
    }
    if (typeof value === 'string') {
      return value.trim().toLowerCase() === 'true';
    }
    return false;
  }

  private readNumber(value: unknown): number | undefined {
    const parsed = this.parseJsonLikeValue(value);
    if (parsed !== value) {
      return this.readNumber(parsed);
    }

    if (typeof value === 'number') {
      return value;
    }
    if (typeof value === 'string') {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : undefined;
    }
    return undefined;
  }

  private asRecord(value: unknown): Record<string, unknown> {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return {};
    }
    return value as Record<string, unknown>;
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }
}
