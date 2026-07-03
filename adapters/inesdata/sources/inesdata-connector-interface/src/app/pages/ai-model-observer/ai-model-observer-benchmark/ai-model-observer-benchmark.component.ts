import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { ModelObserverQueryFilter, ModelObserverTimelineView } from 'src/app/shared/models/model-observer-view.model';
import { ModelObserverReadService } from 'src/app/shared/services/model-observer-read.service';

@Component({
  selector: 'app-ai-model-observer-benchmark',
  templateUrl: './ai-model-observer-benchmark.component.html',
  styleUrls: ['./ai-model-observer-benchmark.component.scss']
})
export class AiModelObserverBenchmarkComponent implements OnInit {
  private readonly benchmarkEvidenceLimit = 10000;

  benchmarkRunId = '';
  timeline: ModelObserverTimelineView | null = null;
  isLoading = false;
  error = '';
  selectedEventType = '';
  statusFilter = '';
  readonly eventTypes = [
    'BENCHMARK_STARTED',
    'BENCHMARK_COMPLETED',
    'BENCHMARK_FAILED',
    'MODEL_EXECUTION_REQUESTED',
    'MODEL_EXECUTION_COMPLETED',
    'MODEL_EXECUTION_FAILED'
  ];

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly modelObserverReadService: ModelObserverReadService
  ) {}

  ngOnInit(): void {
    this.benchmarkRunId = this.route.snapshot.paramMap.get('benchmarkRunId') || '';
    if (!this.benchmarkRunId) {
      this.error = 'Missing benchmarkRunId route parameter.';
      return;
    }

    this.loadBenchmark();
  }

  goBack(): void {
    this.router.navigate(['/ai-model-observer']);
  }

  openAgreementEvidence(agreementId: string | null): void {
    if (!agreementId) {
      return;
    }

    this.router.navigate(['/ai-model-observer/agreements', agreementId]);
  }

  openParticipantSummary(participantId: string | null): void {
    if (!participantId) {
      return;
    }

    this.router.navigate(['/ai-model-observer/participants', participantId]);
  }

  applyFilters(): void {
    this.loadBenchmark({
      eventType: this.selectedEventType,
      status: this.statusFilter
    });
  }

  clearFilters(): void {
    this.selectedEventType = '';
    this.statusFilter = '';
    this.loadBenchmark();
  }

  private loadBenchmark(filter: ModelObserverQueryFilter = {}): void {
    this.isLoading = true;
    this.error = '';
    this.modelObserverReadService.getBenchmarkTimeline(this.benchmarkRunId, {
      ...filter,
      limit: this.benchmarkEvidenceLimit
    }).subscribe({
      next: (timeline) => {
        this.timeline = timeline;
        this.isLoading = false;
      },
      error: () => {
        this.error = 'Failed to load benchmark evidence.';
        this.isLoading = false;
      }
    });
  }
}
