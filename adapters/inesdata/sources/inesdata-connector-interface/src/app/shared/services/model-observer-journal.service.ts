import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { environment } from 'src/environments/environment';
import { resolveModelObserverApiBaseUrl } from '../utils/model-observer-runtime';

export interface ModelObserverJournalEvent {
  eventId?: string;
  eventType: string;
  occurredAt?: string;
  sourceComponent?: string;
  participantId?: string;
  correlationId?: string;
  benchmarkRunId?: string;
  assetId?: string;
  status?: string;
  modelName?: string;
  taskType?: string;
  datasetFingerprint?: string;
  datasetRowCount?: number;
  selectedMetrics?: string[];
  benchmarkSummary?: Record<string, unknown>;
  details?: Record<string, unknown>;
}

@Injectable({
  providedIn: 'root'
})
export class ModelObserverJournalService {
  constructor(private readonly http: HttpClient) {}

  publish(event: ModelObserverJournalEvent): Observable<unknown> {
    const baseUrl = resolveModelObserverApiBaseUrl(environment.runtime);
    if (!baseUrl) {
      return of(null);
    }

    return this.http.post(`${baseUrl}/events`, {
      eventId: event.eventId || this.createId('evt'),
      occurredAt: event.occurredAt || new Date().toISOString(),
      sourceComponent: event.sourceComponent || 'connector-interface:benchmarking',
      participantId: event.participantId || environment.runtime.participantId || null,
      ...event
    }).pipe(
      catchError(() => of(null))
    );
  }

  createId(prefix = 'observer'): string {
    const random = Math.random().toString(36).slice(2, 10);
    return `${prefix}-${Date.now()}-${random}`;
  }
}