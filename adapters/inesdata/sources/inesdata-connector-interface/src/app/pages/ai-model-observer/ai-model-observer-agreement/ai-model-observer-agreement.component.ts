import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { ModelObserverQueryFilter, ModelObserverTimelineView } from 'src/app/shared/models/model-observer-view.model';
import { ModelObserverReadService } from 'src/app/shared/services/model-observer-read.service';

@Component({
  selector: 'app-ai-model-observer-agreement',
  templateUrl: './ai-model-observer-agreement.component.html',
  styleUrls: ['./ai-model-observer-agreement.component.scss']
})
export class AiModelObserverAgreementComponent implements OnInit {
  agreementId = '';
  timeline: ModelObserverTimelineView | null = null;
  isLoading = false;
  error = '';
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
    'BENCHMARK_FAILED'
  ];

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly modelObserverReadService: ModelObserverReadService
  ) {}

  ngOnInit(): void {
    this.agreementId = this.route.snapshot.paramMap.get('agreementId') || '';
    if (!this.agreementId) {
      this.error = 'Missing agreementId route parameter.';
      return;
    }

    this.loadAgreementTimeline();
  }

  goBack(): void {
    this.router.navigate(['/ai-model-observer']);
  }

  openParticipantSummary(participantId: string | null): void {
    if (!participantId) {
      return;
    }

    this.router.navigate(['/ai-model-observer/participants', participantId]);
  }

  openAssetTimeline(assetId: string | null): void {
    if (!assetId) {
      return;
    }

    this.router.navigate(['/ai-model-observer/timeline', assetId]);
  }

  applyFilters(): void {
    this.loadAgreementTimeline({
      eventType: this.selectedEventType,
      status: this.statusFilter
    });
  }

  clearFilters(): void {
    this.selectedEventType = '';
    this.statusFilter = '';
    this.loadAgreementTimeline();
  }

  private loadAgreementTimeline(filter: ModelObserverQueryFilter = {}): void {
    this.isLoading = true;
    this.error = '';
    this.modelObserverReadService.getAgreementTimeline(this.agreementId, filter).subscribe({
      next: (timeline) => {
        this.timeline = timeline;
        this.isLoading = false;
      },
      error: () => {
        this.error = 'Failed to load agreement evidence.';
        this.isLoading = false;
      }
    });
  }
}