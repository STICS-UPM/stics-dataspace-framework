import { Component } from '@angular/core';
import { Router } from '@angular/router';

@Component({
  selector: 'app-ai-model-observer-home',
  templateUrl: './ai-model-observer-home.component.html',
  styleUrls: ['./ai-model-observer-home.component.scss']
})
export class AiModelObserverHomeComponent {
  assetId = '';
  agreementId = '';
  benchmarkRunId = '';
  participantId = '';

  constructor(private readonly router: Router) {}

  openAssetTimeline(): void {
    const normalized = this.assetId.trim();
    if (!normalized) {
      return;
    }

    this.router.navigate(['/ai-model-observer/timeline', normalized]);
  }

  openAgreementEvidence(): void {
    const normalized = this.agreementId.trim();
    if (!normalized) {
      return;
    }

    this.router.navigate(['/ai-model-observer/agreements', normalized]);
  }

  openBenchmarkEvidence(): void {
    const normalized = this.benchmarkRunId.trim();
    if (!normalized) {
      return;
    }

    this.router.navigate(['/ai-model-observer/benchmarks', normalized]);
  }

  openParticipantSummary(): void {
    const normalized = this.participantId.trim();
    if (!normalized) {
      return;
    }

    this.router.navigate(['/ai-model-observer/participants', normalized]);
  }
}