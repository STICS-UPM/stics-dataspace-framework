export interface ModelObserverFilter {
  agreementId?: string;
  participantId?: string;
  eventType?: string;
  status?: string;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}