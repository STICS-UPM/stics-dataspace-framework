import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ModelObserverBenchmark } from '../../../shared/models/model-observer/model-observer-benchmark.model';
import { ModelObserverBenchmarkService } from '../../../shared/services/model-observer/model-observer-benchmark.service';

@Component({
  selector: 'app-model-observer-benchmark-history',
  templateUrl: './model-observer-benchmark-history.component.html',
  styleUrls: ['./model-observer-benchmark-history.component.scss']
})
export class ModelObserverBenchmarkHistoryComponent implements OnInit {
  benchmarkRunId = '';
  benchmark: ModelObserverBenchmark | null = null;
  error = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly benchmarkService: ModelObserverBenchmarkService
  ) {}

  ngOnInit(): void {
    this.benchmarkRunId = this.route.snapshot.paramMap.get('benchmarkRunId') || '';
    if (!this.benchmarkRunId) {
      this.error = 'Missing benchmarkRunId route parameter.';
      return;
    }

    this.benchmarkService.getBenchmarkTimeline(this.benchmarkRunId).subscribe({
      next: (benchmark) => {
        this.benchmark = benchmark;
      },
      error: () => {
        this.error = 'Failed to load benchmark history.';
      }
    });
  }
}