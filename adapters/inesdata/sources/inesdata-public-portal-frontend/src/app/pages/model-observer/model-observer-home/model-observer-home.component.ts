import { Component } from '@angular/core';
import { Router } from '@angular/router';

interface ObserverQuickLinkCard {
  title: string;
  description: string;
  pathHint: string;
  inputKey: 'assetId' | 'agreementId' | 'benchmarkRunId' | 'participantId';
  placeholder: string;
  actionLabel: string;
  routeSegments: string[];
}

@Component({
  selector: 'app-model-observer-home',
  templateUrl: './model-observer-home.component.html',
  styleUrls: ['./model-observer-home.component.scss']
})
export class ModelObserverHomeComponent {
  readonly lookup = {
    assetId: '',
    agreementId: '',
    benchmarkRunId: '',
    participantId: ''
  };

  readonly cards: ObserverQuickLinkCard[] = [
    {
      title: 'Timeline by asset',
      description: 'Inspect all observer events recorded for one model asset.',
      pathHint: '/model-observer/timeline/:assetId',
      inputKey: 'assetId',
      placeholder: 'Enter assetId',
      actionLabel: 'Open timeline',
      routeSegments: ['timeline']
    },
    {
      title: 'Agreement evidence',
      description: 'Review contract-linked evidence grouped by agreement.',
      pathHint: '/model-observer/agreements/:agreementId',
      inputKey: 'agreementId',
      placeholder: 'Enter agreementId',
      actionLabel: 'Open agreement evidence',
      routeSegments: ['agreements']
    },
    {
      title: 'Benchmark history',
      description: 'Inspect benchmark runs and provenance summaries.',
      pathHint: '/model-observer/benchmarks/:benchmarkRunId',
      inputKey: 'benchmarkRunId',
      placeholder: 'Enter benchmarkRunId',
      actionLabel: 'Open benchmark history',
      routeSegments: ['benchmarks']
    },
    {
      title: 'Participant summary',
      description: 'See counts and recent failures by participant.',
      pathHint: '/model-observer/participants/:participantId',
      inputKey: 'participantId',
      placeholder: 'Enter participantId',
      actionLabel: 'Open participant summary',
      routeSegments: ['participants']
    }
  ];

  constructor(private readonly router: Router) {}

  openCard(card: ObserverQuickLinkCard): void {
    const targetId = this.lookup[card.inputKey].trim();
    if (!targetId) {
      return;
    }

    this.router.navigate(['/model-observer', ...card.routeSegments, targetId]);
  }
}