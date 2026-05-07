import { Component, Input } from '@angular/core';
import { ModelObserverEvent } from '../../../models/model-observer/model-observer-event.model';

@Component({
  selector: 'app-model-event-card',
  templateUrl: './model-event-card.component.html',
  styleUrls: ['./model-event-card.component.scss']
})
export class ModelEventCardComponent {
  @Input() event!: ModelObserverEvent;

  get tone(): 'neutral' | 'success' | 'warning' | 'error' {
    const status = `${this.event?.status || ''}`.toLowerCase();
    if (status.includes('fail') || status.includes('error')) {
      return 'error';
    }
    if (status.includes('complete') || status.includes('success')) {
      return 'success';
    }
    if (status.includes('pending') || status.includes('review')) {
      return 'warning';
    }
    return 'neutral';
  }
}