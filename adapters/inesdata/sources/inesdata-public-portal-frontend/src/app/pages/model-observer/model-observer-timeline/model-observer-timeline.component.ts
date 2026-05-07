import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ModelObserverFilter } from '../../../shared/models/model-observer/model-observer-filter.model';
import { ModelObserverTimeline } from '../../../shared/models/model-observer/model-observer-timeline.model';
import { ModelObserverTimelineService } from '../../../shared/services/model-observer/model-observer-timeline.service';

@Component({
  selector: 'app-model-observer-timeline',
  templateUrl: './model-observer-timeline.component.html',
  styleUrls: ['./model-observer-timeline.component.scss']
})
export class ModelObserverTimelineComponent implements OnInit {
  assetId = '';
  timeline: ModelObserverTimeline | null = null;
  isLoading = false;
  error = '';
  readonly eventTypes = [
    'CONTRACT_NEGOTIATION_FINALIZED',
    'TRANSFER_PROCESS_STARTED',
    'TRANSFER_PROCESS_COMPLETED',
    'MODEL_EXECUTION_REQUESTED',
    'MODEL_EXECUTION_COMPLETED',
    'MODEL_EXECUTION_FAILED',
    'BENCHMARK_STARTED',
    'BENCHMARK_COMPLETED',
    'BENCHMARK_FAILED',
    'MODEL_DETAIL_VIEWED'
  ];

  constructor(
    private readonly route: ActivatedRoute,
    private readonly timelineService: ModelObserverTimelineService
  ) {}

  ngOnInit(): void {
    this.assetId = this.route.snapshot.paramMap.get('assetId') || '';
    if (this.assetId) {
      this.loadTimeline();
    } else {
      this.error = 'Missing assetId route parameter.';
    }
  }

  onFilterChanged(filter: ModelObserverFilter): void {
    this.loadTimeline(filter);
  }

  private loadTimeline(filter: ModelObserverFilter = {}): void {
    this.isLoading = true;
    this.error = '';
    this.timelineService.getTimeline(this.assetId, filter).subscribe({
      next: (timeline) => {
        this.timeline = timeline;
        this.isLoading = false;
      },
      error: () => {
        this.error = 'Failed to load model observer timeline.';
        this.isLoading = false;
      }
    });
  }
}