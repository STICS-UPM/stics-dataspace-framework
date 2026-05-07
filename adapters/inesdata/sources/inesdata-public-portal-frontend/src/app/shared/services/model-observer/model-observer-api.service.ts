import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';
import { ModelObserverEvent } from '../../models/model-observer/model-observer-event.model';
import { ModelObserverBenchmark } from '../../models/model-observer/model-observer-benchmark.model';
import { ModelObserverFilter } from '../../models/model-observer/model-observer-filter.model';
import { ModelObserverSummary } from '../../models/model-observer/model-observer-summary.model';
import { ModelObserverTimeline } from '../../models/model-observer/model-observer-timeline.model';

@Injectable({
  providedIn: 'root'
})
export class ModelObserverApiService {
  private readonly baseUrl = `${environment.runtime.strapiUrl}/api/model-observer`;

  constructor(private readonly http: HttpClient) {}

  createEvent(event: Partial<ModelObserverEvent> & { eventType: string; sourceComponent: string }): Observable<unknown> {
    return this.http.post(`${this.baseUrl}/events`, event);
  }

  getTimeline(assetId: string, filter: ModelObserverFilter = {}): Observable<ModelObserverTimeline> {
    return this.http.get<ModelObserverTimeline>(`${this.baseUrl}/timeline/${encodeURIComponent(assetId)}`, {
      params: this.buildParams(filter)
    });
  }

  getAgreementTimeline(agreementId: string, filter: ModelObserverFilter = {}): Observable<ModelObserverTimeline> {
    return this.http.get<ModelObserverTimeline>(`${this.baseUrl}/agreements/${encodeURIComponent(agreementId)}`, {
      params: this.buildParams(filter)
    });
  }

  getBenchmarkTimeline(benchmarkRunId: string, filter: ModelObserverFilter = {}): Observable<ModelObserverBenchmark> {
    return this.http.get<ModelObserverBenchmark>(`${this.baseUrl}/benchmarks/${encodeURIComponent(benchmarkRunId)}`, {
      params: this.buildParams(filter)
    });
  }

  getParticipantSummary(participantId: string): Observable<ModelObserverSummary> {
    return this.http.get<ModelObserverSummary>(`${this.baseUrl}/participants/${encodeURIComponent(participantId)}/summary`);
  }

  private buildParams(filter: ModelObserverFilter): HttpParams {
    let params = new HttpParams();

    Object.entries(filter).forEach(([key, value]) => {
      if (value !== undefined && value !== null && `${value}`.trim() !== '') {
        params = params.set(key, `${value}`);
      }
    });

    return params;
  }
}