import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { ModelObserverFilter } from '../../../models/model-observer/model-observer-filter.model';

@Component({
  selector: 'app-model-timeline-filter',
  templateUrl: './model-timeline-filter.component.html',
  styleUrls: ['./model-timeline-filter.component.scss']
})
export class ModelTimelineFilterComponent {
  @Input() eventTypes: string[] = [];
  @Output() filterChanged = new EventEmitter<ModelObserverFilter>();

  readonly form: FormGroup;

  constructor(private readonly fb: FormBuilder) {
    this.form = this.fb.group({
      eventType: [''],
      status: [''],
      from: [''],
      to: ['']
    });
  }

  apply(): void {
    this.filterChanged.emit(this.form.value);
  }

  clear(): void {
    this.form.reset({ eventType: '', status: '', from: '', to: '' });
    this.filterChanged.emit({});
  }
}