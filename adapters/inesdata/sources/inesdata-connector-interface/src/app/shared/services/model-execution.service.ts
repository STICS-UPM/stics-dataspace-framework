import { HttpClient, HttpResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { forkJoin, Observable, of, throwError } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { environment } from 'src/environments/environment';
import { AiModelExecutionInputFeature, AiModelExecutionItem, ModelExecutionRequestPayload, ModelExecutionResponsePayload } from '../models/ai-model-execution-item';
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
      switchMap(total => this.catalogBrowserService.getPaginatedDataOffers(this.buildQuerySpec(total || this.minPageSize)).pipe(
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

  private buildQuerySpec(total: number): QuerySpec {
    return {
      offset: 0,
      limit: Math.max(total, this.minPageSize)
    };
  }

  private mapOwnAsset(asset: Asset): AiModelExecutionItem {
    const assetData = this.normalizeAssetData(this.readLocalAssetData(asset));
    const properties = this.asRecord((asset as any)?.properties);
    const dataAddress = this.readLocalDataAddress(asset);
    const metadataNode = [assetData, properties, asset as unknown as Record<string, unknown>];
    const inputSchema = this.extractInputSchema(metadataNode);
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
      tasks: this.collectMetadataValues(metadataNode, ['daimo:task', 'https://w3id.org/daimo/ns#task', 'https://pionera.ai/edc/daimo#task', 'task']),
      algorithms: this.collectMetadataValues(metadataNode, ['daimo:algorithm', 'https://w3id.org/daimo/ns#algorithm', 'https://pionera.ai/edc/daimo#algorithm', 'algorithm']),
      frameworks: this.collectMetadataValues(metadataNode, ['daimo:framework', 'https://w3id.org/daimo/ns#framework', 'https://pionera.ai/edc/daimo#framework', 'framework']),
      inputFeatures: this.extractInputFeatures(metadataNode, inputSchema),
      inputSchema,
      inputExample: this.extractInputExample(metadataNode),
      rawAsset: asset
    };
  }

  private mapFederatedOffer(offer: DataOffer, hasAgreement: boolean): AiModelExecutionItem {
    const properties = this.asRecord(offer?.properties);
    const assetData = this.normalizeAssetData(properties.assetData);
    const metadataNode = [assetData, properties, offer as unknown as Record<string, unknown>];
    const inputSchema = this.extractInputSchema(metadataNode);
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
      tasks: this.collectMetadataValues(metadataNode, ['daimo:task', 'https://w3id.org/daimo/ns#task', 'https://pionera.ai/edc/daimo#task', 'task']),
      algorithms: this.collectMetadataValues(metadataNode, ['daimo:algorithm', 'https://w3id.org/daimo/ns#algorithm', 'https://pionera.ai/edc/daimo#algorithm', 'algorithm']),
      frameworks: this.collectMetadataValues(metadataNode, ['daimo:framework', 'https://w3id.org/daimo/ns#framework', 'https://pionera.ai/edc/daimo#framework', 'framework']),
      inputFeatures: this.extractInputFeatures(metadataNode, inputSchema),
      inputSchema,
      inputExample: this.extractInputExample(metadataNode),
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
      'daimo:input_schema',
      'https://w3id.org/daimo/ns#input_schema',
      'https://pionera.ai/edc/daimo#input_schema',
      'input_schema',
      'inputSchema'
    ]);

    if (value !== undefined) {
      return this.parseJsonLikeValue(value);
    }

    const directFeatures = this.findFirstValue(node, [
      'daimo:input_features',
      'https://w3id.org/daimo/ns#input_features',
      'https://pionera.ai/edc/daimo#input_features',
      'input_features',
      'inputFeatures'
    ]);
    return this.parseJsonLikeValue(directFeatures);
  }

  private extractInputFeatures(node: unknown, inputSchema: unknown): AiModelExecutionInputFeature[] {
    const directFeatures = this.parseInputFeatureCollection(this.findFirstValue(node, [
      'daimo:input_features',
      'https://w3id.org/daimo/ns#input_features',
      'https://pionera.ai/edc/daimo#input_features',
      'input_features',
      'inputFeatures'
    ]));

    if (directFeatures.length > 0) {
      return directFeatures;
    }

    const schemaFeatures = this.parseInputFeatureCollection(inputSchema);
    if (schemaFeatures.length > 0) {
      return schemaFeatures;
    }

    return this.buildInputFeaturesFromSchema(inputSchema);
  }

  private extractInputExample(node: unknown): unknown {
    const value = this.findFirstValue(node, [
      'daimo:input_example',
      'https://w3id.org/daimo/ns#input_example',
      'https://pionera.ai/edc/daimo#input_example',
      'input_example',
      'inputExample'
    ]);
    return this.parseJsonLikeValue(value);
  }

  private collectMetadataValues(node: unknown, keys: string[]): string[] {
    const values: string[] = [];
    this.walkMetadata(node, new Set(keys), values);
    return this.unique(values);
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
    const parsed = this.parseJsonLikeValue(value);
    const schemaRecord = this.asRecord(parsed);
    const rawFields = Array.isArray(parsed)
      ? parsed
      : Array.isArray(schemaRecord.features)
        ? schemaRecord.features
        : Array.isArray(schemaRecord.fields)
          ? schemaRecord.fields
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
      .filter(item => !!this.firstText(item.name, item.field, item.path))
      .map(item => ({
        name: this.firstText(item.name, item.field, item.path),
        type: this.firstText(item.type, item.dataType, item.dtype) || 'string',
        required: item.required !== undefined ? this.readBoolean(item.required) : !this.readBoolean(item.nullable),
        description: this.firstText(item.description, item.title) || undefined,
        minValue: this.readNumber(item.minValue ?? item.min ?? item.minimum),
        maxValue: this.readNumber(item.maxValue ?? item.max ?? item.maximum)
      }));
  }

  private buildInputFeaturesFromSchema(schema: unknown): AiModelExecutionInputFeature[] {
    const schemaRecord = this.resolveSchemaRoot(this.asRecord(this.parseJsonLikeValue(schema)));
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
        minValue: this.readNumber(schemaRecord.minValue ?? schemaRecord.min ?? schemaRecord.minimum),
        maxValue: this.readNumber(schemaRecord.maxValue ?? schemaRecord.max ?? schemaRecord.maximum)
      });
    });
  }

  private resolveSchemaRoot(schemaNode: Record<string, unknown>): Record<string, unknown> {
    const nestedKeys = ['input', 'payload', 'body', 'requestBody'];
    for (const key of nestedKeys) {
      const nested = this.asRecord(schemaNode[key]);
      if (this.isRecord(nested['properties']) || Array.isArray(nested['required'])) {
        return nested;
      }
    }

    return schemaNode;
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
    if (typeof value === 'boolean') {
      return value;
    }
    if (typeof value === 'string') {
      return value.trim().toLowerCase() === 'true';
    }
    return false;
  }

  private readNumber(value: unknown): number | undefined {
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
