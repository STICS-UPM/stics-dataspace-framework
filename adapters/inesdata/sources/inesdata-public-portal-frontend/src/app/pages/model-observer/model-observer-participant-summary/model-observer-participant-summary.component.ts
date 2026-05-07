import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ModelObserverSummary } from '../../../shared/models/model-observer/model-observer-summary.model';
import { ModelObserverSummaryService } from '../../../shared/services/model-observer/model-observer-summary.service';

@Component({
  selector: 'app-model-observer-participant-summary',
  templateUrl: './model-observer-participant-summary.component.html',
  styleUrls: ['./model-observer-participant-summary.component.scss']
})
export class ModelObserverParticipantSummaryComponent implements OnInit {
  participantId = '';
  summary: ModelObserverSummary | null = null;
  error = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly summaryService: ModelObserverSummaryService
  ) {}

  ngOnInit(): void {
    this.participantId = this.route.snapshot.paramMap.get('participantId') || '';
    if (!this.participantId) {
      this.error = 'Missing participantId route parameter.';
      return;
    }

    this.summaryService.getParticipantSummary(this.participantId).subscribe({
      next: (summary) => {
        this.summary = summary;
      },
      error: () => {
        this.error = 'Failed to load participant summary.';
      }
    });
  }

  get totalKeys(): string[] {
    return Object.keys(this.summary?.totalsByEventType || {});
  }
}