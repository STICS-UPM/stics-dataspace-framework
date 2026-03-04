import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpResponse } from '@angular/common/http';
import { Observable, forkJoin, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { environment } from '../../../environments/environment';
import { MlBrowserService } from './ml-browser.service';
import { MLAsset } from '../models/ml-asset';
import { ConnectorContextService } from './connector-context.service';

export interface ModelExecutionRequest {
  assetId: string;
  payload: any;
  method?: string;
  path?: string;
  headers?: Record<string, string>;
}

export interface ModelExecutionResponse {
  status: 'success' | 'error';
  assetId: string;
  output?: any;
  error?: string;
  timestamp: string;
}

export interface ExecutableAsset {
  id: string;
  name: string;
  execution_path: string;
  contentType?: string;
  tags?: string[];
}

@Injectable({
  providedIn: 'root'
})
export class ModelExecutionService {
  private readonly http = inject(HttpClient);
  private readonly mlBrowserService = inject(MlBrowserService);
  private readonly connectorContextService = inject(ConnectorContextService);

  private get inferUrl(): string {
    return this.connectorContextService.getInferApiUrl();
  }

  executeModel(request: ModelExecutionRequest): Observable<ModelExecutionResponse> {
    const body: Record<string, unknown> = {
      assetId: request.assetId,
      method: request.method || 'POST',
      path: request.path || '/infer',
      headers: request.headers || { 'Content-Type': 'application/json' },
      payload: request.payload
    };

    return this.http.post<any>(this.inferUrl, body, { observe: 'response' }).pipe(
      map((response: HttpResponse<any>) => ({
        status: response.status >= 200 && response.status < 300 ? 'success' : 'error',
        assetId: request.assetId,
        output: response.body,
        timestamp: new Date().toISOString()
      }))
    );
  }

  getExecutableAssets(): Observable<ExecutableAsset[]> {
    return forkJoin({
      assets: this.mlBrowserService.getPaginatedMLAssets(),
      agreedAssetIds: this.getAgreedAssetIds()
    }).pipe(
      map(({ assets, agreedAssetIds }) =>
        assets.filter((asset) => this.isExecutableAsset(asset, agreedAssetIds))
      ),
      map((assets) => assets.map((asset) => this.toExecutableAsset(asset)))
    );
  }

  private isExecutableAsset(asset: MLAsset, agreedAssetIds: Set<string>): boolean {
    const contentType = (asset.contentType || '').toLowerCase();
    const tags = (asset.keywords || []).map(t => t.toLowerCase());
    const isTechnicallyExecutable =
      contentType.includes('application/json') || tags.includes('inference') || tags.includes('endpoint');

    const isLocal = !!asset.isLocal;
    const hasAgreement = agreedAssetIds.has(asset.id);

    return isTechnicallyExecutable && (isLocal || hasAgreement);
  }

  private toExecutableAsset(asset: MLAsset): ExecutableAsset {
    return {
      id: asset.id,
      name: asset.name,
      execution_path: this.extractInferencePath(asset),
      contentType: asset.contentType,
      tags: asset.keywords
    };
  }

  private extractInferencePath(asset: MLAsset): string {
    const candidates = [
      'https://pionera.ai/edc/daimo#inference_path',
      'daimo:inference_path',
      'inference_path',
      'inferencePath',
      'path'
    ];

    const fromObject = (obj?: Record<string, unknown>) => {
      if (!obj) return undefined;
      for (const key of candidates) {
        const value = obj[key];
        if (typeof value === 'string' && value.trim()) {
          return value.trim();
        }
      }
      return undefined;
    };

    const direct = fromObject(asset.rawProperties);
    if (direct) return this.normalizePath(direct);

    const props = (asset.rawProperties?.['properties'] as Record<string, unknown>) || undefined;
    const nested = fromObject(props);
    if (nested) return this.normalizePath(nested);

    return '/infer';
  }

  private normalizePath(path: string): string {
    return path.startsWith('/') ? path : `/${path}`;
  }

  private getAgreedAssetIds(): Observable<Set<string>> {
    const body = {
      '@context': { '@vocab': 'https://w3id.org/edc/v0.0.1/ns/' },
      filterExpression: []
    };
    const url = `${this.connectorContextService.getManagementApiUrl()}/v3/contractagreements/request`;

    return this.http.post<any>(url, body).pipe(
      map((response) => {
        const agreements = this.normalizeAgreements(response);
        const ids = new Set<string>();
        for (const agreement of agreements) {
          const assetId = this.extractAgreementAssetId(agreement);
          if (assetId) {
            ids.add(assetId);
          }
        }
        return ids;
      }),
      catchError((error) => {
        console.warn('[ModelExecution] Failed to query contract agreements. External assets will be hidden.', error);
        return of(new Set<string>());
      })
    );
  }

  private normalizeAgreements(response: any): any[] {
    if (!response) return [];
    if (Array.isArray(response)) return response;
    if (Array.isArray(response.results)) return response.results;
    if (Array.isArray(response.items)) return response.items;
    if (Array.isArray(response.contractAgreements)) return response.contractAgreements;
    if (Array.isArray(response['@graph'])) return response['@graph'];
    return [response];
  }

  private extractAgreementAssetId(agreement: any): string | null {
    const direct = agreement?.assetId || agreement?.['edc:assetId'] || agreement?.['https://w3id.org/edc/v0.0.1/ns/assetId'];
    if (typeof direct === 'string' && direct.trim().length > 0) {
      return direct.trim();
    }

    const assetNode = agreement?.asset || agreement?.['edc:asset'];
    if (typeof assetNode === 'string' && assetNode.trim().length > 0) {
      return assetNode.trim();
    }
    if (assetNode && typeof assetNode === 'object') {
      const nested = assetNode['@id'] || assetNode['id'] || assetNode['assetId'];
      if (typeof nested === 'string' && nested.trim().length > 0) {
        return nested.trim();
      }
    }

    return null;
  }
}
