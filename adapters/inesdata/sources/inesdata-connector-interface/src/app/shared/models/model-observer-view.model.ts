export interface ModelObserverEventView {
  eventId: string;
  eventType: string;
  occurredAt: string;
  sourceComponent: string;
  participantId: string | null;
  correlationId: string | null;
  assetId: string | null;
  agreementId: string | null;
  benchmarkRunId: string | null;
  status: string | null;
  modelName: string | null;
  httpStatus: number | null;
  latencyMs: number | null;
  details: Record<string, unknown> | null;
}

export interface ModelObserverTimelineView {
  items: ModelObserverEventView[];
  total: number;
  limit: number;
  offset: number;
}

export interface ModelObserverParticipantSummaryView {
  participantId: string;
  totalsByEventType: Record<string, number>;
  recentFailures: number;
  latestEvent: ModelObserverEventView | null;
}

export interface ModelObserverQueryFilter {
  correlationId?: string;
  eventType?: string;
  status?: string;
}