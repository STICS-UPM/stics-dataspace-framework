import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ModelObserverFilter } from '../../models/model-observer/model-observer-filter.model';
import { ModelObserverTimeline } from '../../models/model-observer/model-observer-timeline.model';
import { ModelObserverApiService } from './model-observer-api.service';

@Injectable({
  providedIn: 'root'
})
export class ModelObserverTimelineService {
  constructor(private readonly api: ModelObserverApiService) {}

  getTimeline(assetId: string, filter: ModelObserverFilter = {}): Observable<ModelObserverTimeline> {
    return this.api.getTimeline(assetId, filter);
  }

  getAgreementTimeline(agreementId: string, filter: ModelObserverFilter = {}): Observable<ModelObserverTimeline> {
    return this.api.getAgreementTimeline(agreementId, filter);
  }
}