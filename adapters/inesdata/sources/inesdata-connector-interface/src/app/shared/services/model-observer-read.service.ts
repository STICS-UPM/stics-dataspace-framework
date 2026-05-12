import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, throwError } from 'rxjs';
import { environment } from 'src/environments/environment';
import { resolveModelObserverApiBaseUrl } from '../utils/model-observer-runtime';
import {
  ModelObserverParticipantSummaryView,
  ModelObserverQueryFilter,
  ModelObserverTimelineView
} from '../models/model-observer-view.model';

@Injectable({
  providedIn: 'root'
})
export class ModelObserverReadService {
  constructor(private readonly http: HttpClient) {}

  getAssetTimeline(assetId: string, filter: ModelObserverQueryFilter = {}): Observable<ModelObserverTimelineView> {
    const baseUrl = this.resolveBaseUrl();
    if (!baseUrl) {
      return throwError(() => new Error('Model observer backend URL is not configured.'));
    }

    return this.http.get<ModelObserverTimelineView>(`${baseUrl}/timeline/${encodeURIComponent(assetId)}`, {
      params: this.buildParams(filter)
    });
  }

  getAgreementTimeline(agreementId: string, filter: ModelObserverQueryFilter = {}): Observable<ModelObserverTimelineView> {
    const baseUrl = this.resolveBaseUrl();
    if (!baseUrl) {
      return throwError(() => new Error('Model observer backend URL is not configured.'));
    }

    return this.http.get<ModelObserverTimelineView>(`${baseUrl}/agreements/${encodeURIComponent(agreementId)}`, {
      params: this.buildParams(filter)
    });
  }

  getBenchmarkTimeline(benchmarkRunId: string, filter: ModelObserverQueryFilter = {}): Observable<ModelObserverTimelineView> {
    const baseUrl = this.resolveBaseUrl();
    if (!baseUrl) {
      return throwError(() => new Error('Model observer backend URL is not configured.'));
    }

    return this.http.get<ModelObserverTimelineView>(`${baseUrl}/benchmarks/${encodeURIComponent(benchmarkRunId)}`, {
      params: this.buildParams(filter)
    });
  }

  getParticipantSummary(participantId: string): Observable<ModelObserverParticipantSummaryView> {
    const baseUrl = this.resolveBaseUrl();
    if (!baseUrl) {
      return throwError(() => new Error('Model observer backend URL is not configured.'));
    }

    return this.http.get<ModelObserverParticipantSummaryView>(`${baseUrl}/participants/${encodeURIComponent(participantId)}/summary`);
  }

  private resolveBaseUrl(): string {
    return resolveModelObserverApiBaseUrl(environment.runtime);
  }

  private buildParams(filter: ModelObserverQueryFilter): HttpParams {
    let params = new HttpParams();

    Object.entries(filter).forEach(([key, value]) => {
      if (value !== undefined && value !== null && `${value}`.trim() !== '') {
        params = params.set(key, `${value}`.trim());
      }
    });

    return params;
  }
}