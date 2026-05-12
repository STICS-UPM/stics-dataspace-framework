import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-model-observer-badge',
  templateUrl: './model-observer-badge.component.html',
  styleUrls: ['./model-observer-badge.component.scss']
})
export class ModelObserverBadgeComponent {
  @Input() text = '';
  @Input() tone: 'neutral' | 'success' | 'warning' | 'error' = 'neutral';
}