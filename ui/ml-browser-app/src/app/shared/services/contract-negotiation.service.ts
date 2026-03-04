import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, from, lastValueFrom } from 'rxjs';
import { map } from 'rxjs/operators';
import { environment } from '../../../environments/environment';
import { JSON_LD_DEFAULT_CONTEXT } from '@think-it-labs/edc-connector-client';
import { ConnectorContextService } from './connector-context.service';

/**
 * Contract Negotiation Service
 * 
 * Handles contract negotiation operations with the EDC connector
 */
@Injectable({
  providedIn: 'root'
})
export class ContractNegotiationService {
  private readonly http = inject(HttpClient);
  private readonly connectorContextService = inject(ConnectorContextService);

  private get baseUrl(): string {
    return `${this.connectorContextService.getManagementApiUrl()}${environment.runtime.service.contractNegotiation.baseUrl}`;
  }

  /**
   * Get all contract negotiations
   */
  getAll(): Observable<any[]> {
    const body = {
      '@context': JSON_LD_DEFAULT_CONTEXT,
      'filterExpression': []
    };

    return from(lastValueFrom(
      this.http.post<any[]>(`${this.baseUrl}${environment.runtime.service.contractNegotiation.getAll}`, body)
    ));
  }

  /**
   * Get all contract agreements.
   */
  getAllAgreements(): Observable<any[]> {
    const body = {
      '@context': JSON_LD_DEFAULT_CONTEXT,
      filterExpression: []
    };

    return from(lastValueFrom(
      this.http.post<any[]>(
        `${this.connectorContextService.getManagementApiUrl()}/v3/contractagreements/request`,
        body
      )
    )).pipe(
      map((response) => this.normalizeAgreements(response))
    );
  }

  /**
   * Returns asset IDs that already have a contract agreement.
   */
  getAgreedAssetIds(): Observable<Set<string>> {
    return this.getAllAgreements().pipe(
      map((agreements) => {
        const ids = new Set<string>();
        for (const agreement of agreements) {
          const assetId = this.extractAgreementAssetId(agreement);
          if (assetId) {
            ids.add(assetId);
          }
        }
        return ids;
      })
    );
  }

  /**
   * Get a specific contract negotiation by ID
   */
  get(id: string): Observable<any> {
    if (!id) {
      throw new Error('Contract negotiation ID is required');
    }

    return from(lastValueFrom(
      this.http.get<any>(`${this.baseUrl}${environment.runtime.service.contractNegotiation.get}${id}`)
    ));
  }

  /**
   * Initiate a new contract negotiation
   */
  initiate(negotiationRequest: any): Observable<any> {
    const body = {
      ...negotiationRequest,
      '@context': JSON_LD_DEFAULT_CONTEXT
    };

    return from(lastValueFrom(
      this.http.post<any>(this.baseUrl, body)
    ));
  }

  /**
   * Terminate a contract negotiation
   */
  terminate(id: string, reason?: string): Observable<any> {
    if (!id) {
      throw new Error('Contract negotiation ID is required');
    }

    const body = {
      '@context': JSON_LD_DEFAULT_CONTEXT,
      '@id': id,
      'reason': reason || 'Terminated by user'
    };

    return from(lastValueFrom(
      this.http.post<any>(`${this.baseUrl}/${id}/terminate`, body)
    ));
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
