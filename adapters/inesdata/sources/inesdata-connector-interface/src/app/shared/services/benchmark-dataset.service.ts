import { Injectable } from '@angular/core';
import { catchError, forkJoin, lastValueFrom, map, Observable, of, switchMap } from 'rxjs';
import {
  BenchmarkDatasetAsset,
  BenchmarkDatasetMapping
} from '../models/benchmark-dataset-asset';
import { Asset, QuerySpec } from '../models/edc-connector-entities';
import { DataOffer } from '../models/data-offer';
import { AssetService } from './asset.service';
import { CatalogBrowserService } from './catalog-browser.service';
import { ContractAgreementService } from './contractAgreement.service';
import { ContractNegotiationService } from './contractNegotiation.service';
import { EndpointDataAddress, TransferProcessService } from './transferProcess.service';
import { environment } from 'src/environments/environment';

interface BenchmarkDatasetTransferContext {
  agreementId: string;
  assetId: string;
  connectorId: string;
  counterPartyAddress: string;
  transferType: string;
}

@Injectable({
  providedIn: 'root'
})
export class BenchmarkDatasetService {
  private readonly minPageSize = 100;
  private readonly currentParticipantId = `${environment.runtime.participantId || ''}`.trim().toLowerCase();
  private readonly transferPollIntervalMs = 1000;
  private readonly transferPollTimeoutMs = 120000;

  constructor(
    private readonly assetService: AssetService,
    private readonly catalogBrowserService: CatalogBrowserService,
    private readonly contractAgreementService: ContractAgreementService,
    private readonly contractNegotiationService: ContractNegotiationService,
    private readonly transferProcessService: TransferProcessService
  ) {}

  getBenchmarkDatasets(): Observable<BenchmarkDatasetAsset[]> {
    return forkJoin({
      ownAssets: this.loadOwnAssets(),
      federatedOffers: this.loadFederatedOffers(),
      agreementAssetIds: this.loadAgreementAssetIds()
    }).pipe(
      map(({ ownAssets, federatedOffers, agreementAssetIds }) => {
        const ownDatasets = ownAssets
          .map(asset => this.mapOwnAsset(asset))
          .filter(asset => this.looksLikeDatasetAsset(asset));

        const federatedDatasets = federatedOffers
          .filter(offer => !this.isCurrentConnectorOffer(offer))
          .map(offer => this.mapFederatedOffer(offer, agreementAssetIds.has(`${offer.assetId}`)))
          .filter(asset => asset.hasAgreement)
          .filter(asset => this.looksLikeDatasetAsset(asset));

        return [...ownDatasets, ...federatedDatasets].sort((left, right) => {
          if (left.source !== right.source) {
            return left.source === 'own' ? -1 : 1;
          }
          return left.name.localeCompare(right.name);
        });
      })
    );
  }

  extractInlineDatasetPayload(asset: BenchmarkDatasetAsset): unknown | null {
    const keys = [
      'daimo:benchmark_dataset',
      'https://pionera.ai/edc/daimo#benchmark_dataset',
      'https://w3id.org/daimo/ns#benchmark_dataset',
      'benchmark_dataset',
      'benchmarkDataset'
    ];

    return this.findFirstValue(this.metadataSources(asset), keys) ?? null;
  }

  async loadDatasetPayload(asset: BenchmarkDatasetAsset): Promise<unknown> {
    const inlinePayload = this.extractInlineDatasetPayload(asset);
    if (inlinePayload !== null && inlinePayload !== undefined) {
      return inlinePayload;
    }

    if (asset.isLocal) {
      throw new Error('Local dataset asset does not include inline benchmark rows. Upload the file manually or add daimo:benchmark_dataset metadata.');
    }

    if (!asset.hasAgreement) {
      throw new Error('Selected external dataset has no finalized agreement.');
    }

    const transferContext = await this.resolveTransferContext(asset);
    const transferId = await this.startPullTransfer(transferContext);
    await this.waitForTransferReady(transferId);
    const dataAddress = await this.waitForTransferDataAddress(transferId);
    const blob = await lastValueFrom(this.transferProcessService.downloadEndpointData(dataAddress));
    return blob.text();
  }

  extractDatasetMapping(asset: BenchmarkDatasetAsset): BenchmarkDatasetMapping | null {
    const sources = this.metadataSources(asset);
    const raw = this.findFirstValue(sources, [
      'daimo:benchmark_dataset_mapping',
      'https://pionera.ai/edc/daimo#benchmark_dataset_mapping',
      'https://w3id.org/daimo/ns#benchmark_dataset_mapping',
      'benchmark_dataset_mapping',
      'benchmarkDatasetMapping',
      'mapping'
    ]);
    const mapping = this.asRecord(this.parseJsonLikeValue(raw));

    const input = this.unique([
      ...this.extractFieldNameList(mapping['input']),
      ...this.extractFieldNameList(this.findFirstDirectValue(sources, [
        'daimo:input',
        'https://pionera.ai/edc/daimo#input',
        'https://w3id.org/daimo/ns#input',
        'input'
      ]))
    ]);
    const label = this.firstText(
      mapping['label'],
      this.findFirstDirectValue(sources, [
        'daimo:label',
        'https://pionera.ai/edc/daimo#label',
        'https://w3id.org/daimo/ns#label',
        'label'
      ])
    );

    if (input.length === 0 && !label) {
      return null;
    }

    return { input, label };
  }

  resolveDatasetFileName(asset: BenchmarkDatasetAsset): string {
    const name = (asset.fileName || asset.name || asset.id || 'benchmark-dataset').trim();
    if (/\.(jsonl|json|csv)$/i.test(name)) {
      return name;
    }

    const hints = [asset.format, asset.contentType].join(' ').toLowerCase();
    if (hints.includes('jsonl') || hints.includes('ndjson')) return `${name}.jsonl`;
    if (hints.includes('csv')) return `${name}.csv`;
    return `${name}.json`;
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

  private loadContractAgreements(): Observable<any[]> {
    return this.contractAgreementService.count().pipe(
      catchError(() => of(0)),
      switchMap(total => this.contractAgreementService.queryAllAgreements(this.buildQuerySpec(total || this.minPageSize)).pipe(
        catchError(() => of([]))
      ))
    );
  }

  private loadContractNegotiations(): Observable<any[]> {
    return this.contractNegotiationService.queryNegotiations(this.buildQuerySpec(this.minPageSize)).pipe(
      catchError(() => of([]))
    );
  }

  private buildQuerySpec(total: number): QuerySpec {
    return {
      offset: 0,
      limit: Math.max(total, this.minPageSize)
    };
  }

  private mapOwnAsset(asset: Asset): BenchmarkDatasetAsset {
    const rawProperties = this.asRecord((asset as any)?.properties);
    const dataAddress = this.readLocalDataAddress(asset);
    const metadataNode = [rawProperties, this.normalizeAssetData(rawProperties['assetData']), asset as unknown as Record<string, unknown>];
    const id = `${(asset as any)?.id || (asset as any)?.['@id'] || ''}`;
    const assetType = this.firstText(
      this.readLocalProperty(asset, ['assetType', 'edc:assetType', 'https://w3id.org/edc/v0.0.1/ns/assetType']),
      this.findFirstValue(metadataNode, [
        'daimo:asset_type',
        'https://pionera.ai/edc/daimo#asset_type',
        'https://w3id.org/daimo/ns#asset_type',
        'asset_type',
        'daimo:assetType',
        'assetType'
      ])
    ) || '';

    return {
      id,
      name: this.firstText(this.readLocalProperty(asset, ['name']), id) || id,
      description: this.firstText(
        this.readLocalProperty(asset, ['description', 'dcterms:description', 'http://purl.org/dc/terms/description']),
        this.readLocalProperty(asset, ['shortDescription'])
      ),
      provider: environment.runtime.participantId || 'this-connector',
      source: 'own',
      isLocal: true,
      hasAgreement: true,
      assetType,
      contentType: this.firstText(this.readLocalProperty(asset, ['contenttype', 'dcat:mediaType'])) || '',
      format: this.firstText(this.readLocalProperty(asset, ['format', 'dcterms:format', 'http://purl.org/dc/terms/format'])) || '',
      storageType: this.firstText(dataAddress['type'], dataAddress['@type'], dataAddress['edc:type']) || '',
      fileName: this.firstText(dataAddress['keyName'], dataAddress['s3Key'], dataAddress['fileName'], dataAddress['filename']) || '',
      tags: this.unique([
        ...this.collectMetadataValues(metadataNode, [
          'daimo:tags',
          'https://pionera.ai/edc/daimo#tags',
          'https://w3id.org/daimo/ns#tags',
          'dcat:keyword',
          'http://www.w3.org/ns/dcat#keyword',
          'keywords'
        ])
      ]),
      rawProperties,
      rawAsset: asset
    };
  }

  private mapFederatedOffer(offer: DataOffer, hasAgreement: boolean): BenchmarkDatasetAsset {
    const properties = this.asRecord(offer?.properties);
    const rawPropertiesFromOffer = this.asRecord(properties['rawProperties']);
    const rawProperties = Object.keys(rawPropertiesFromOffer).length > 0 ? rawPropertiesFromOffer : properties;
    const metadataNode = [
      properties,
      rawProperties,
      this.normalizeAssetData(properties['assetData']),
      this.normalizeAssetData(rawProperties['assetData'])
    ];
    const assetType = this.firstText(
      properties['assetType'],
      rawProperties['assetType'],
      this.findFirstValue(metadataNode, [
        'daimo:asset_type',
        'https://pionera.ai/edc/daimo#asset_type',
        'https://w3id.org/daimo/ns#asset_type',
        'asset_type',
        'daimo:assetType',
        'assetType'
      ])
    ) || '';

    return {
      id: `${offer.assetId}`,
      name: this.firstText(properties['name'], offer.assetId) || `${offer.assetId}`,
      description: this.firstText(properties['description'], properties['shortDescription']),
      provider: this.firstText(properties['participantId'], offer.originator) || 'federated-provider',
      source: 'federated',
      isLocal: false,
      hasAgreement,
      assetType,
      contentType: this.firstText(properties['contenttype']) || '',
      format: this.firstText(properties['format']) || '',
      storageType: this.firstText(properties['storageType']) || '',
      fileName: this.firstText(properties['fileName']) || '',
      tags: this.unique([
        ...this.collectMetadataValues(metadataNode, [
          'daimo:tags',
          'https://pionera.ai/edc/daimo#tags',
          'https://w3id.org/daimo/ns#tags',
          'dcat:keyword',
          'http://www.w3.org/ns/dcat#keyword',
          'keywords'
        ])
      ]),
      rawProperties,
      rawOffer: offer
    };
  }

  private looksLikeDatasetAsset(asset: BenchmarkDatasetAsset): boolean {
    const hasDatasetIdentity = this.isDatasetAssetType(asset.assetType);
    const hasBenchmarkMetadata =
      this.extractDatasetMapping(asset) !== null
      || this.extractInlineDatasetPayload(asset) !== null;

    return hasDatasetIdentity && hasBenchmarkMetadata && !this.hasInferenceMetadata(asset);
  }

  private isDatasetAssetType(assetType: string): boolean {
    const normalized = assetType.toLowerCase().replace(/[^a-z0-9]/g, '');
    return normalized === 'dataset' || normalized === 'benchmarkdataset' || normalized === 'validationdataset';
  }

  private hasInferenceMetadata(asset: BenchmarkDatasetAsset): boolean {
    const value = this.findFirstValue(this.metadataSources(asset), [
      'https://pionera.ai/edc/daimo#inference_path',
      'https://w3id.org/daimo/ns#inference_path',
      'daimo:inference_path',
      'inference_path',
      'inferencePath'
    ]);
    return typeof value === 'string' && value.trim().length > 0;
  }

  private async resolveTransferContext(asset: BenchmarkDatasetAsset): Promise<BenchmarkDatasetTransferContext> {
    const agreements = await lastValueFrom(this.loadContractAgreements());
    const matchingAgreements = agreements.filter(agreement => this.readAgreementAssetId(agreement) === asset.id);
    const preferredAgreement = matchingAgreements.find(agreement => {
      const providerId = this.readAgreementProviderId(agreement).toLowerCase();
      return providerId && providerId === asset.provider.toLowerCase();
    }) || matchingAgreements[0];

    if (!preferredAgreement) {
      throw new Error(`No finalized consumer contract agreement found for dataset asset "${asset.id}".`);
    }

    const agreementId = this.readAgreementId(preferredAgreement);
    if (!agreementId) {
      throw new Error(`Dataset agreement for asset "${asset.id}" does not expose an agreement id.`);
    }

    const negotiations = await lastValueFrom(this.loadContractNegotiations());
    const negotiation = this.findNegotiationForAgreement(negotiations, agreementId);
    const counterPartyAddress = this.readNegotiationCounterPartyAddress(negotiation)
      || this.firstText(asset.rawOffer?.endpointUrl);
    if (!counterPartyAddress) {
      throw new Error(`Dataset agreement "${agreementId}" does not expose a counterparty address.`);
    }

    return {
      agreementId,
      assetId: this.readAgreementAssetId(preferredAgreement) || asset.id,
      connectorId: this.readAgreementProviderId(preferredAgreement) || asset.provider,
      counterPartyAddress,
      transferType: this.resolvePullTransferType(asset)
    };
  }

  private async startPullTransfer(transferContext: BenchmarkDatasetTransferContext): Promise<string> {
    const response = await lastValueFrom(this.transferProcessService.initiateTransfer({
      assetId: transferContext.assetId,
      connectorId: transferContext.connectorId,
      counterPartyAddress: transferContext.counterPartyAddress,
      contractId: transferContext.agreementId,
      protocol: 'dataspace-protocol-http',
      transferType: transferContext.transferType
    } as any));
    const transferId = this.firstText(response?.id, response?.['@id']);

    if (!transferId) {
      throw new Error('Connector did not return a transfer process id.');
    }

    return transferId;
  }

  private async waitForTransferReady(transferId: string): Promise<void> {
    const deadline = Date.now() + this.transferPollTimeoutMs;
    const readyStates = ['STARTED', 'COMPLETED', 'IN_PROGRESS', 'STREAMING'];
    const failedStates = ['ERROR', 'TERMINATED', 'SUSPENDED', 'DEPROVISIONED'];
    let lastState = '';

    while (Date.now() < deadline) {
      const stateResponse = await lastValueFrom(this.transferProcessService.getTransferProcessState(transferId));
      lastState = this.firstText(stateResponse?.state, stateResponse?.['edc:state']).toUpperCase();

      if (readyStates.includes(lastState)) {
        return;
      }

      if (failedStates.includes(lastState)) {
        throw new Error(`Dataset transfer failed with state ${lastState}.`);
      }

      await this.sleep(this.transferPollIntervalMs);
    }

    throw new Error(`Dataset transfer timed out${lastState ? ` while in state ${lastState}` : ''}.`);
  }

  private async waitForTransferDataAddress(transferId: string): Promise<EndpointDataAddress> {
    const deadline = Date.now() + this.transferPollTimeoutMs;
    let lastError: unknown = null;

    while (Date.now() < deadline) {
      try {
        const dataAddress = await lastValueFrom(this.transferProcessService.getTransferDataAddress(transferId));
        if (this.hasEndpoint(dataAddress)) {
          return dataAddress;
        }
      } catch (error) {
        lastError = error;
      }

      await this.sleep(this.transferPollIntervalMs);
    }

    const suffix = lastError instanceof Error ? ` ${lastError.message}` : '';
    throw new Error(`Transfer completed, but no EDR download endpoint became available.${suffix}`);
  }

  private hasEndpoint(dataAddress: EndpointDataAddress): boolean {
    return !!this.firstText(
      dataAddress?.endpoint,
      dataAddress?.['edc:endpoint'],
      dataAddress?.['https://w3id.org/edc/v0.0.1/ns/endpoint'],
      dataAddress?.endpointUrl,
      dataAddress?.['edc:endpointUrl']
    );
  }

  private resolvePullTransferType(asset: BenchmarkDatasetAsset): string {
    const transferType = this.firstText(
      this.findFirstValue(asset.rawProperties, [
        'transferType',
        'edc:transferType',
        'https://w3id.org/edc/v0.0.1/ns/transferType',
        'dcterms:format',
        'http://purl.org/dc/terms/format',
        'format'
      ]),
      asset.format,
      asset.storageType
    );

    return transferType.toLowerCase().includes('pull') ? transferType : 'HttpData-PULL';
  }

  private findNegotiationForAgreement(negotiations: any[], agreementId: string): any | null {
    const candidates = negotiations
      .filter(negotiation => this.readNegotiationAgreementId(negotiation) === agreementId)
      .filter(negotiation => {
        const state = this.readNegotiationState(negotiation);
        return !state || state === 'FINALIZED' || state === 'VERIFIED';
      })
      .sort((left, right) => this.readTimestamp(right) - this.readTimestamp(left));

    return candidates[0] || null;
  }

  private readAgreementId(agreement: any): string {
    return this.firstText(
      agreement?.id,
      agreement?.['@id'],
      agreement?.contractAgreementId,
      agreement?.agreementId
    );
  }

  private readAgreementAssetId(agreement: any): string {
    return this.firstText(
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
  }

  private readAgreementProviderId(agreement: any): string {
    return this.firstText(
      agreement?.providerId,
      agreement?.['edc:providerId'],
      agreement?.['https://w3id.org/edc/v0.0.1/ns/providerId'],
      agreement?.assigner,
      agreement?.['edc:assigner']
    );
  }

  private readNegotiationAgreementId(negotiation: any): string {
    return this.firstText(
      negotiation?.contractAgreementId,
      negotiation?.agreementId,
      negotiation?.['edc:contractAgreementId'],
      negotiation?.['edc:agreementId'],
      negotiation?.['https://w3id.org/edc/v0.0.1/ns/contractAgreementId'],
      negotiation?.['https://w3id.org/edc/v0.0.1/ns/agreementId']
    );
  }

  private readNegotiationCounterPartyAddress(negotiation: any): string {
    return this.firstText(
      negotiation?.counterPartyAddress,
      negotiation?.protocolAddress,
      negotiation?.['edc:counterPartyAddress'],
      negotiation?.['edc:protocolAddress'],
      negotiation?.['https://w3id.org/edc/v0.0.1/ns/counterPartyAddress'],
      negotiation?.['https://w3id.org/edc/v0.0.1/ns/protocolAddress']
    );
  }

  private readNegotiationState(negotiation: any): string {
    return this.firstText(
      negotiation?.state,
      negotiation?.['edc:state'],
      negotiation?.['https://w3id.org/edc/v0.0.1/ns/state']
    ).toUpperCase();
  }

  private readTimestamp(value: any): number {
    return Number(this.firstText(
      value?.updatedAt,
      value?.createdAt,
      value?.stateTimestamp,
      value?.['edc:updatedAt'],
      value?.['edc:createdAt'],
      value?.['https://w3id.org/edc/v0.0.1/ns/updatedAt'],
      value?.['https://w3id.org/edc/v0.0.1/ns/createdAt']
    )) || 0;
  }

  private sleep(durationMs: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, durationMs));
  }

  private metadataSources(asset: BenchmarkDatasetAsset): Record<string, unknown>[] {
    const sources: Record<string, unknown>[] = [];
    this.addMetadataSource(sources, asset.rawProperties);
    this.addMetadataSource(sources, this.asRecord(asset.rawProperties['properties']));
    this.addMetadataSource(sources, this.asRecord(asset.rawProperties['assetData']));
    this.addMetadataSource(sources, this.normalizeAssetData(asset.rawProperties['assetData']));

    return sources;
  }

  private addMetadataSource(target: Record<string, unknown>[], source: unknown): void {
    const record = this.asRecord(source);
    if (!this.isRecord(record)) {
      return;
    }
    target.push(record);

    Object.values(record).forEach(value => {
      const nested = this.asRecord(this.parseJsonLikeValue(value));
      if (this.isRecord(nested)) {
        target.push(nested);
      }
    });
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

  private isCurrentConnectorOffer(offer: DataOffer): boolean {
    const participantId = `${offer?.properties?.participantId || offer?.originator || ''}`.trim().toLowerCase();
    return participantId.length > 0 && participantId === this.currentParticipantId;
  }

  private readLocalProperty(asset: Asset, keys: string[]): unknown {
    const properties = (asset as any)?.properties;
    if (!properties) {
      return undefined;
    }

    for (const key of keys) {
      if (typeof properties.optionalValue === 'function' && !key.includes(':') && !key.startsWith('http')) {
        const optionalValue = properties.optionalValue('edc', key);
        if (optionalValue !== undefined && optionalValue !== null) {
          return optionalValue;
        }
      }

      const direct = properties[key];
      if (direct !== undefined && direct !== null) {
        return direct;
      }
    }
    return undefined;
  }

  private readLocalDataAddress(asset: Asset): Record<string, unknown> {
    const assetRecord = asset as any;
    return this.asRecord(this.parseJsonLikeValue(
      assetRecord?.dataAddress
      || assetRecord?.['dataAddress']
      || assetRecord?.['edc:dataAddress']
      || assetRecord?.['https://w3id.org/edc/v0.0.1/ns/dataAddress']
    ));
  }

  private normalizeAssetData(assetData: unknown): unknown {
    return this.parseJsonLikeValue(assetData);
  }

  private collectMetadataValues(node: unknown, keys: string[]): string[] {
    return this.extractTextList(this.findFirstValue(node, keys));
  }

  private extractFieldNameList(value: unknown): string[] {
    const parsed = this.parseJsonLikeValue(value);
    const fields: string[] = [];
    this.collectFieldNames(parsed, fields);
    return this.unique(fields);
  }

  private collectFieldNames(value: unknown, target: string[]): void {
    if (value === undefined || value === null) {
      return;
    }

    if (Array.isArray(value)) {
      value.forEach(item => this.collectFieldNames(item, target));
      return;
    }

    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      `${value}`.split(',').map(item => item.trim()).filter(Boolean).forEach(item => target.push(item));
      return;
    }

    if (!this.isRecord(value)) {
      return;
    }

    if (value['@value'] !== undefined) {
      this.collectFieldNames(value['@value'], target);
      return;
    }

    const fieldName = this.firstText(value['name'], value['field'], value['path'], value['column']);
    if (fieldName) {
      target.push(fieldName);
    }
  }

  private findFirstDirectValue(sources: Record<string, unknown>[], keys: string[]): unknown {
    for (const source of sources) {
      for (const key of keys) {
        const value = source[key];
        if (value !== undefined && value !== null) {
          return value;
        }
      }
    }

    return undefined;
  }

  private findFirstValue(node: unknown, keys: string[]): unknown {
    if (node === undefined || node === null) {
      return undefined;
    }

    if (Array.isArray(node)) {
      for (const item of node) {
        const found = this.findFirstValue(item, keys);
        if (found !== undefined) {
          return found;
        }
      }
      return undefined;
    }

    if (typeof node !== 'object') {
      return undefined;
    }

    const record = node as Record<string, unknown>;
    for (const key of keys) {
      if (record[key] !== undefined && record[key] !== null) {
        return record[key];
      }
    }

    for (const value of Object.values(record)) {
      const found = this.findFirstValue(this.parseJsonLikeValue(value), keys);
      if (found !== undefined) {
        return found;
      }
    }

    return undefined;
  }

  private parseJsonLikeValue(value: unknown): unknown {
    if (typeof value !== 'string') {
      return value;
    }

    const trimmed = value.trim();
    if (!trimmed.length) {
      return value;
    }

    if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) {
      return value;
    }

    try {
      return JSON.parse(trimmed);
    } catch {
      return value;
    }
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
