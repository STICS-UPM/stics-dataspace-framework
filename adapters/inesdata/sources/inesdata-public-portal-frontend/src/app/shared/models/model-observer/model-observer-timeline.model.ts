import { ModelObserverEvent } from './model-observer-event.model';

export interface ModelObserverTimeline {
  items: ModelObserverEvent[];
  total: number;
  limit: number;
  offset: number;
}