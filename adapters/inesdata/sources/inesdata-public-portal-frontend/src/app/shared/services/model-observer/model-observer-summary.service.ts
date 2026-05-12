import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ModelObserverSummary } from '../../models/model-observer/model-observer-summary.model';
import { ModelObserverApiService } from './model-observer-api.service';

@Injectable({
  providedIn: 'root'
})
export class ModelObserverSummaryService {
  constructor(private readonly api: ModelObserverApiService) {}

  getParticipantSummary(participantId: string): Observable<ModelObserverSummary> {
    return this.api.getParticipantSummary(participantId);
  }
}