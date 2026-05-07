import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { ModelObserverParticipantSummaryView } from 'src/app/shared/models/model-observer-view.model';
import { ModelObserverReadService } from 'src/app/shared/services/model-observer-read.service';

@Component({
  selector: 'app-ai-model-observer-participant',
  templateUrl: './ai-model-observer-participant.component.html',
  styleUrls: ['./ai-model-observer-participant.component.scss']
})
export class AiModelObserverParticipantComponent implements OnInit {
  participantId = '';
  summary: ModelObserverParticipantSummaryView | null = null;
  isLoading = false;
  error = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly modelObserverReadService: ModelObserverReadService
  ) {}

  ngOnInit(): void {
    this.participantId = this.route.snapshot.paramMap.get('participantId') || '';
    if (!this.participantId) {
      this.error = 'Missing participantId route parameter.';
      return;
    }

    this.loadSummary();
  }

  get totalKeys(): string[] {
    return Object.keys(this.summary?.totalsByEventType || {});
  }

  goBack(): void {
    this.router.navigate(['/ai-model-observer']);
  }

  openAssetTimeline(assetId: string | null): void {
    if (!assetId) {
      return;
    }

    this.router.navigate(['/ai-model-observer/timeline', assetId]);
  }

  openAgreementEvidence(agreementId: string | null): void {
    if (!agreementId) {
      return;
    }

    this.router.navigate(['/ai-model-observer/agreements', agreementId]);
  }

  openBenchmarkEvidence(benchmarkRunId: string | null): void {
    if (!benchmarkRunId) {
      return;
    }

    this.router.navigate(['/ai-model-observer/benchmarks', benchmarkRunId]);
  }

  private loadSummary(): void {
    this.isLoading = true;
    this.error = '';
    this.modelObserverReadService.getParticipantSummary(this.participantId).subscribe({
      next: (summary) => {
        this.summary = summary;
        this.isLoading = false;
      },
      error: () => {
        this.error = 'Failed to load participant summary.';
        this.isLoading = false;
      }
    });
  }
}