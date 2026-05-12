import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ModelObserverTimeline } from '../../../shared/models/model-observer/model-observer-timeline.model';
import { ModelObserverTimelineService } from '../../../shared/services/model-observer/model-observer-timeline.service';

@Component({
  selector: 'app-model-observer-agreement',
  templateUrl: './model-observer-agreement.component.html',
  styleUrls: ['./model-observer-agreement.component.scss']
})
export class ModelObserverAgreementComponent implements OnInit {
  agreementId = '';
  timeline: ModelObserverTimeline | null = null;
  error = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly timelineService: ModelObserverTimelineService
  ) {}

  ngOnInit(): void {
    this.agreementId = this.route.snapshot.paramMap.get('agreementId') || '';
    if (!this.agreementId) {
      this.error = 'Missing agreementId route parameter.';
      return;
    }

    this.timelineService.getAgreementTimeline(this.agreementId).subscribe({
      next: (timeline) => {
        this.timeline = timeline;
      },
      error: () => {
        this.error = 'Failed to load agreement evidence.';
      }
    });
  }
}