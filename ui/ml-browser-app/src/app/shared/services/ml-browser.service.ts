import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable, forkJoin, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { environment } from '../../../environments/environment';
import { MLAsset } from '../models/ml-asset';
import { MLAssetFilter } from './ml-assets.service';
import { ConnectorContextService } from './connector-context.service';

@Injectable({
  providedIn: 'root'
})
export class MlBrowserService {

  private readonly httpClient = inject(HttpClient);
  private readonly connectorContextService = inject(ConnectorContextService);
  private readonly FILTER_URL = environment.runtime.filterApiUrl || `${environment.runtime.consumerApiUrl}/api/filter/catalog`;

  /**
   * Retrieves ML assets using the filtering extension.
   */
  getPaginatedMLAssets(filters?: MLAssetFilter, searchTerm?: string): Observable<MLAsset[]> {
    return forkJoin({
      external: this.fetchExternalCatalogAssets(filters, searchTerm).pipe(
        catchError((error) => {
          console.warn('[ML Browser Service] External catalog fetch failed, continuing with local assets only.', error);
          return of([] as MLAsset[]);
        })
      ),
      local: this.fetchLocalAssets().pipe(
        catchError((error) => {
          console.warn('[ML Browser Service] Local asset fetch failed, continuing with external assets only.', error);
          return of([] as MLAsset[]);
        })
      )
    }).pipe(
      map(({ external, local }) => this.mergeAssets(local, external)),
      map((assets) => this.applyClientFilters(assets, filters, searchTerm))
    );
  }

  count(): Observable<number> {
    return this.getPaginatedMLAssets().pipe(map(assets => assets.length));
  }

  /**
   * Fetch raw catalog items (used in catalog views)
   */
  getCatalog(querySpec: { offset: number; limit: number }): Observable<any[]> {
    const body = {
      '@context': { '@vocab': 'https://w3id.org/edc/v0.0.1/ns/' },
      counterPartyAddress: this.connectorContextService.getCounterPartyProtocolUrl(),
      protocol: environment.runtime.catalogProtocol,
      querySpec
    };

    return this.httpClient.post<any[]>(`${this.connectorContextService.getManagementApiUrl()}/v3/catalog/request`, body);
  }

  getCatalogCount(): Observable<number> {
    return this.httpClient.post<number>(`${this.connectorContextService.getManagementApiUrl()}/v3/catalog/request/count`, {});
  }

  private buildCatalogRequestBody(): Record<string, unknown> {
    return {
      '@context': { '@vocab': 'https://w3id.org/edc/v0.0.1/ns/' },
      counterPartyAddress: this.connectorContextService.getCounterPartyProtocolUrl(),
      protocol: environment.runtime.catalogProtocol
    };
  }

  private fetchExternalCatalogAssets(filters?: MLAssetFilter, searchTerm?: string): Observable<MLAsset[]> {
    const query = this.buildFilterQuery(filters, searchTerm);
    const url = query ? `${this.FILTER_URL}?${query}` : this.FILTER_URL;
    const body = this.buildCatalogRequestBody();

    console.log('[ML Browser Service] Calling filter catalog:', url);
    return this.httpClient.post<any>(url, body).pipe(
      map(response => this.parseCatalogResponse(response))
    );
  }

  private fetchLocalAssets(): Observable<MLAsset[]> {
    const body = {
      '@context': { '@vocab': 'https://w3id.org/edc/v0.0.1/ns/' },
      offset: 0,
      limit: 1000
    };
    const url = `${this.connectorContextService.getManagementApiUrl()}/v3/assets/request`;

    return this.httpClient.post<any[]>(url, body).pipe(
      map((response) => {
        if (!response) {
          return [];
        }
        const entries = Array.isArray(response) ? response : [response];
        return entries.map((asset) => this.parseLocalAsset(asset));
      })
    );
  }

  private buildFilterQuery(filters?: MLAssetFilter, searchTerm?: string): string {
    const params: string[] = [];
    params.push('profile=daimo');

    if (searchTerm) {
      params.push(`q=${encodeURIComponent(searchTerm)}`);
    }

    if (filters?.tasks?.length) {
      params.push(`task=${encodeURIComponent(filters.tasks.join(','))}`);
    }
    if (filters?.libraries?.length) {
      params.push(`library=${encodeURIComponent(filters.libraries.join(','))}`);
    }
    if (filters?.frameworks?.length) {
      params.push(`library=${encodeURIComponent(filters.frameworks.join(','))}`);
    }
    if (filters?.formats?.length) {
      params.push(`filter=contenttype=${encodeURIComponent(filters.formats.join(','))}`);
    }

    return params.join('&');
  }

  private parseCatalogResponse(response: any): MLAsset[] {
    if (!response) return [];

    const datasets = response['dcat:dataset'] || response['dataset'] || [];
    const list = Array.isArray(datasets) ? datasets : [datasets];
    const catalogParticipantId = this.extractCatalogParticipantId(response);

    return list.map((dataset: any) => this.parseCatalogDataset(dataset, catalogParticipantId));
  }

  private parseCatalogDataset(dataset: any, catalogParticipantId?: string): MLAsset {
    const id = dataset['@id'] || dataset['id'] || 'unknown';
    const name = dataset['name'] || id;

    const daimoTags = dataset['https://pionera.ai/edc/daimo#tags'] || dataset['daimo:tags'] || [];
    const keywords = Array.isArray(daimoTags) ? daimoTags : [daimoTags].filter(Boolean);

    const pipelineTag = dataset['https://pionera.ai/edc/daimo#pipeline_tag'] || dataset['daimo:pipeline_tag'];
    const libraryName = dataset['https://pionera.ai/edc/daimo#library_name'] || dataset['daimo:library_name'];

    const contentType = dataset['contenttype'] || dataset['https://pionera.ai/edc/daimo#contenttype'] || '';
    const storageInfo = this.extractStorageInfoFromCatalogDataset(dataset);
    const transferFormat = this.extractTransferFormatFromCatalogDataset(dataset);
    const byteSize = this.extractDatasetByteSize(dataset);

    const participantId = this.extractParticipantId(dataset, catalogParticipantId);
    const policyRaw = dataset['odrl:hasPolicy'];
    const contractOffers = Array.isArray(policyRaw) ? policyRaw : (policyRaw ? [policyRaw] : []);
    const description = this.buildAssetDescription({
      task: pipelineTag,
      library: libraryName,
      contentType
    });

    return {
      id: String(id),
      name: String(name),
      version: 'N/A',
      description,
      shortDescription: description,
      assetType: 'machineLearning',
      contentType: String(contentType),
      byteSize,
      format: transferFormat,
      keywords: keywords.map((k: any) => String(k)),
      tasks: pipelineTag ? [String(pipelineTag)] : [],
      subtasks: [],
      algorithms: [],
      libraries: libraryName ? [String(libraryName)] : [],
      frameworks: libraryName ? [String(libraryName)] : [],
      modelType: '',
      storageType: storageInfo.storageType,
      fileName: storageInfo.fileName,
      owner: participantId,
      isLocal: false,
      hasContractOffers: contractOffers.length > 0,
      contractOffers,
      endpointUrl: undefined,
      participantId,
      assetData: dataset,
      rawProperties: dataset,
      originator: 'Federated Catalog'
    } as MLAsset;
  }

  private extractTransferFormatFromCatalogDataset(dataset: any): string {
    const distributionRaw = dataset['dcat:distribution'] || dataset['distribution'];
    const distributions = Array.isArray(distributionRaw) ? distributionRaw : (distributionRaw ? [distributionRaw] : []);
    for (const distribution of distributions) {
      const format = distribution?.['dct:format']?.['@id'] || distribution?.['dct:format']?.['id'];
      if (typeof format === 'string' && format.trim().length > 0) {
        return format.trim();
      }
    }
    return '';
  }

  private extractDatasetByteSize(dataset: any): string {
    const candidates = [
      dataset?.['dcat:byteSize'],
      dataset?.['byteSize'],
      dataset?.['https://pionera.ai/edc/daimo#byteSize']
    ];
    for (const value of candidates) {
      if (value === undefined || value === null) {
        continue;
      }
      if (typeof value === 'number' || typeof value === 'string') {
        const asText = String(value).trim();
        if (asText.length > 0) {
          return asText;
        }
      }
    }
    return '';
  }

  private extractCatalogParticipantId(catalog: any): string {
    const keys = [
      'dspace:participantId',
      'participantId',
      'participant_id',
      'https://w3id.org/dspace/v0.8/participantId',
      'https://w3id.org/dspace/2024/1/participantId',
      'https://w3id.org/dspace/2025/1/participantId'
    ];
    for (const key of keys) {
      const value = catalog?.[key];
      if (typeof value === 'string' && value.trim().length > 0) {
        return value.trim();
      }
    }
    return '';
  }

  private extractParticipantId(dataset: any, catalogParticipantId?: string): string {
    const candidateKeys = [
      'dspace:participantId',
      'participantId',
      'participant_id',
      'https://w3id.org/dspace/v0.8/participantId',
      'https://w3id.org/dspace/2024/1/participantId',
      'https://w3id.org/dspace/2025/1/participantId'
    ];

    const readText = (obj: any): string => {
      if (!obj || typeof obj !== 'object') {
        return '';
      }
      for (const key of candidateKeys) {
        const value = obj[key];
        if (typeof value === 'string' && value.trim().length > 0) {
          return value.trim();
        }
      }
      return '';
    };

    const direct = readText(dataset);
    if (direct) {
      return direct;
    }

    const props = dataset?.properties || dataset?.['edc:properties'];
    const fromProps = readText(props);
    if (fromProps) {
      return fromProps;
    }

    if (catalogParticipantId && catalogParticipantId.trim().length > 0) {
      return catalogParticipantId.trim();
    }

    // Fallback so owner badge is always visible for external assets.
    return this.connectorContextService.getCurrentRole() === 'consumer' ? 'provider' : 'consumer';
  }

  private extractStorageInfoFromCatalogDataset(dataset: any): { storageType: string; fileName: string } {
    const readText = (obj: any, keys: string[]): string => {
      if (!obj || typeof obj !== 'object') {
        return '';
      }
      for (const key of keys) {
        const value = obj[key];
        if (typeof value === 'string' && value.trim().length > 0) {
          return value.trim();
        }
      }
      return '';
    };

    const normalizeType = (value: string): string => {
      if (!value) {
        return '';
      }
      const lower = value.toLowerCase();
      if (lower.includes('http')) {
        return 'HttpData';
      }
      if (lower.includes('s3') || lower.includes('amazon')) {
        return 'AmazonS3';
      }
      if (lower.includes('dataspaceprototypestore')) {
        return 'DataSpacePrototypeStore';
      }
      return value;
    };

    const explicitType = normalizeType(readText(dataset, [
      'storageType',
      'daimo:storage_type',
      'https://pionera.ai/edc/daimo#storage_type',
      'edc:dataAddressType'
    ]));
    if (explicitType) {
      return { storageType: explicitType, fileName: '' };
    }

    const distributionRaw = dataset['dcat:distribution'] || dataset['distribution'];
    const distributions = Array.isArray(distributionRaw) ? distributionRaw : (distributionRaw ? [distributionRaw] : []);

    for (const distribution of distributions) {
      const transferFormat = readText(distribution?.['dct:format'], ['@id', 'id']);
      if (transferFormat) {
        return {
          storageType: normalizeType(transferFormat),
          fileName: readText(distribution, ['fileName', 'name', 's3Key', 'keyName'])
        };
      }

      const type = normalizeType(readText(distribution, ['type', 'edc:dataAddressType']));
      const fileName = readText(distribution, ['fileName', 'name', 's3Key', 'keyName']);
      if (type) {
        return { storageType: type, fileName };
      }

      const accessServiceRaw = distribution?.['dcat:accessService'] || distribution?.['accessService'];
      const accessServices = Array.isArray(accessServiceRaw) ? accessServiceRaw : (accessServiceRaw ? [accessServiceRaw] : []);
      for (const service of accessServices) {
        const endpoint = readText(service, [
          'dcat:endpointURL',
          'dcat:endpointUrl',
          'endpointURL',
          'endpointUrl',
          'baseUrl',
          'endpoint'
        ]);
        const bucket = readText(service, ['bucketName']);
        const keyName = readText(service, ['s3Key', 'keyName', 'fileName', 'name']);
        if (bucket || keyName) {
          return { storageType: 'AmazonS3', fileName: keyName };
        }
        if (endpoint) {
          return { storageType: 'HttpData', fileName: '' };
        }
      }
    }

    return { storageType: '', fileName: '' };
  }

  private parseLocalAsset(asset: any): MLAsset {
    const properties = (asset?.['edc:properties'] || asset?.properties || {}) as Record<string, unknown>;
    const dataAddress = (asset?.['edc:dataAddress'] || asset?.dataAddress || {}) as Record<string, unknown>;
    const id = asset?.['@id'] || asset?.id || 'unknown-local';

    const sources: Array<Record<string, unknown>> = [properties, asset];

    const readText = (keys: string[], fallback = ''): string => {
      for (const source of sources) {
        for (const key of keys) {
          const value = source[key];
          if (typeof value === 'string' && value.trim().length > 0) {
            return value;
          }
        }
      }
      return fallback;
    };

    const readList = (keys: string[]): string[] => {
      for (const source of sources) {
        for (const key of keys) {
          const value = source[key];
          if (Array.isArray(value)) {
            return value.map(v => String(v)).filter(Boolean);
          }
          if (typeof value === 'string' && value.trim().length > 0) {
            return [value];
          }
        }
      }
      return [];
    };

    const readListFromDaimo = (key: string): string[] => {
      return readList([`daimo:${key}`, `https://pionera.ai/edc/daimo#${key}`]);
    };

    const name = readText(['name', 'asset:prop:name', 'dct:title'], String(id));
    const contentType = readText([
      'contenttype',
      'asset:prop:contenttype',
      'daimo:contenttype',
      'https://pionera.ai/edc/daimo#contenttype'
    ]);
    const explicitDescription = readText(['description', 'asset:prop:description', 'dcterms:description']);
    const shortDescription = readText(['shortDescription', 'asset:prop:shortDescription'], explicitDescription);
    const version = readText(['version', 'asset:prop:version'], 'N/A');
    const task = readText(['daimo:pipeline_tag', 'pipeline_tag', 'https://pionera.ai/edc/daimo#pipeline_tag']);
    const library = readText(['daimo:library_name', 'library_name', 'https://pionera.ai/edc/daimo#library_name']);
    const keywords = readList([
      'daimo:tags',
      'https://pionera.ai/edc/daimo#tags',
      'dcat:keyword',
      'asset:prop:keywords'
    ]);

    const tasks = [
      ...(task ? [task] : []),
      ...readListFromDaimo('task')
    ];
    const subtasks = readListFromDaimo('subtask');
    const algorithms = readListFromDaimo('algorithm');
    const libraries = [
      ...(library ? [library] : []),
      ...readListFromDaimo('library')
    ];
    const frameworks = readListFromDaimo('framework');
    const storageType = String(dataAddress['type'] || dataAddress['@type'] || '');
    const fileName = String(dataAddress['keyName'] || dataAddress['s3Key'] || dataAddress['fileName'] || '');

    const description = this.buildAssetDescription({
      task: tasks[0] || '',
      library: libraries[0] || frameworks[0] || '',
      contentType
    }, explicitDescription);

    const unique = (values: string[]) => Array.from(new Set(values.filter(Boolean)));

    return {
      id: String(id),
      name,
      version,
      description,
      shortDescription: shortDescription || description,
      assetType: readText(['asset:prop:type', 'type'], 'machineLearning'),
      contentType,
      byteSize: readText(['asset:prop:byteSize', 'byteSize']),
      format: readText(['format', 'asset:prop:format', 'daimo:format'], storageType || ''),
      keywords: unique(keywords),
      tasks: unique(tasks),
      subtasks: unique(subtasks),
      algorithms: unique(algorithms),
      libraries: unique(libraries),
      frameworks: unique(frameworks),
      modelType: '',
      storageType,
      fileName,
      owner: String(this.connectorContextService.getCurrentRole()),
      isLocal: true,
      hasContractOffers: false,
      contractOffers: [],
      endpointUrl: undefined,
      participantId: '',
      assetData: asset,
      rawProperties: {
        ...asset,
        properties
      },
      originator: 'Local Connector'
    } as MLAsset;
  }

  private mergeAssets(localAssets: MLAsset[], externalAssets: MLAsset[]): MLAsset[] {
    const merged = new Map<string, MLAsset>();
    [...externalAssets, ...localAssets].forEach((asset) => {
      if (!asset?.id) {
        return;
      }
      // Keep local and external entries distinct even if asset IDs match.
      const key = `${asset.id}::${asset.isLocal ? 'local' : 'external'}`;
      merged.set(key, asset);
    });
    return Array.from(merged.values());
  }

  private buildAssetDescription(
    info: { task?: string; library?: string; contentType?: string },
    fallback = ''
  ): string {
    if (fallback && fallback.trim().length > 0) {
      return fallback.trim();
    }
    return '';
  }

  private applyClientFilters(assets: MLAsset[], filters?: MLAssetFilter, searchTerm?: string): MLAsset[] {
    let result = [...assets];
    const term = (searchTerm || '').trim().toLowerCase();

    if (term) {
      result = result.filter(asset =>
        (asset.name || '').toLowerCase().includes(term) ||
        (asset.description || '').toLowerCase().includes(term) ||
        (asset.shortDescription || '').toLowerCase().includes(term) ||
        (asset.keywords || []).some(k => String(k).toLowerCase().includes(term))
      );
    }

    if (filters?.tasks?.length) {
      result = result.filter(asset => (asset.tasks || []).some(t => filters.tasks!.includes(t)));
    }
    if (filters?.libraries?.length) {
      result = result.filter(asset => (asset.libraries || []).some(l => filters.libraries!.includes(l)));
    }
    if (filters?.frameworks?.length) {
      result = result.filter(asset => (asset.frameworks || []).some(f => filters.frameworks!.includes(f)));
    }
    if (filters?.formats?.length) {
      result = result.filter(asset => !!asset.format && filters.formats!.includes(asset.format));
    }
    if (filters?.assetSources?.length) {
      result = result.filter(asset => {
        const source = asset.isLocal ? 'Local Asset' : 'External Asset';
        return filters.assetSources!.includes(source);
      });
    }

    return result;
  }
}
