import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ModelObserverBenchmark } from '../../models/model-observer/model-observer-benchmark.model';
import { ModelObserverFilter } from '../../models/model-observer/model-observer-filter.model';
import { ModelObserverApiService } from './model-observer-api.service';

@Injectable({
  providedIn: 'root'
})
export class ModelObserverBenchmarkService {
  constructor(private readonly api: ModelObserverApiService) {}

  getBenchmarkTimeline(benchmarkRunId: string, filter: ModelObserverFilter = {}): Observable<ModelObserverBenchmark> {
    return this.api.getBenchmarkTimeline(benchmarkRunId, filter);
  }
}