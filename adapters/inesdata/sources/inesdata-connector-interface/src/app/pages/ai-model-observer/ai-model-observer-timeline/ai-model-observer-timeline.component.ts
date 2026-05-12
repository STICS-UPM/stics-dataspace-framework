import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { ModelObserverQueryFilter, ModelObserverTimelineView } from 'src/app/shared/models/model-observer-view.model';
import { ModelObserverReadService } from 'src/app/shared/services/model-observer-read.service';

@Component({
  selector: 'app-ai-model-observer-timeline',
  templateUrl: './ai-model-observer-timeline.component.html',
  styleUrls: ['./ai-model-observer-timeline.component.scss']
})
export class AiModelObserverTimelineComponent implements OnInit {
  assetId = '';
  timeline: ModelObserverTimelineView | null = null;
  isLoading = false;
  error = '';
  correlationIdFilter = '';
  selectedEventType = '';
  statusFilter = '';
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
    private readonly router: Router,
    private readonly modelObserverReadService: ModelObserverReadService
  ) {}

  ngOnInit(): void {
    this.assetId = this.route.snapshot.paramMap.get('assetId') || '';
    if (!this.assetId) {
      this.error = 'Missing assetId route parameter.';
      return;
    }

    this.correlationIdFilter = this.route.snapshot.queryParamMap.get('correlationId') || '';
    this.loadTimeline(this.buildFilter());
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
    this.loadTimeline(this.buildFilter());
  }

  clearFilters(): void {
    this.correlationIdFilter = '';
    this.selectedEventType = '';
    this.statusFilter = '';
    this.loadTimeline();
  }

  hasActiveCorrelationFilter(): boolean {
    return this.correlationIdFilter.trim().length > 0;
  }

  private buildFilter(): ModelObserverQueryFilter {
    return {
      correlationId: this.correlationIdFilter,
      eventType: this.selectedEventType,
      status: this.statusFilter
    };
  }

  private loadTimeline(filter: ModelObserverQueryFilter = {}): void {
    this.isLoading = true;
    this.error = '';
    this.modelObserverReadService.getAssetTimeline(this.assetId, filter).subscribe({
      next: (timeline) => {
        this.timeline = timeline;
        this.isLoading = false;
      },
      error: () => {
        this.error = 'Failed to load observer timeline.';
        this.isLoading = false;
      }
    });
  }
}