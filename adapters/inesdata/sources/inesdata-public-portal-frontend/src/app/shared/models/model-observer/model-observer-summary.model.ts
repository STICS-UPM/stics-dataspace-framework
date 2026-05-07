import { ModelObserverEvent } from './model-observer-event.model';

export interface ModelObserverSummary {
  participantId: string;
  totalsByEventType: Record<string, number>;
  recentFailures: number;
  latestEvent: ModelObserverEvent | null;
}