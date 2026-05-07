'use strict';

const { randomUUID } = require('crypto');

const EVENT_TYPES = new Set([
  'CONTRACT_NEGOTIATION_FINALIZED',
  'TRANSFER_PROCESS_STARTED',
  'TRANSFER_PROCESS_COMPLETED',
  'MODEL_EXECUTION_REQUESTED',
  'MODEL_EXECUTION_COMPLETED',
  'MODEL_EXECUTION_FAILED',
  'BENCHMARK_STARTED',
  'BENCHMARK_COMPLETED',
  'BENCHMARK_FAILED',
  'MODEL_BROWSER_SEARCHED',
  'MODEL_BROWSER_FILTERED',
  'MODEL_DETAIL_VIEWED'
]);

const TEXT_FIELDS = [
  'eventId',
  'eventType',
  'occurredAt',
  'sourceComponent',
  'participantId',
  'actorType',
  'actorId',
  'correlationId',
  'processId',
  'assetId',
  'agreementId',
  'negotiationId',
  'transferProcessId',
  'benchmarkRunId',
  'status',
  'modelName',
  'providerParticipantId',
  'consumerParticipantId',
  'executionMode',
  'endpointKind',
  'taskType',
  'datasetFingerprint',
  'payloadHash',
  'responseHash'
];

function asTrimmedText(value) {
  if (value === undefined || value === null) {
    return null;
  }

  const normalized = `${value}`.trim();
  return normalized.length > 0 ? normalized : null;
}

function asInteger(value) {
  if (value === undefined || value === null || value === '') {
    return null;
  }

  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function asNumber(value) {
  if (value === undefined || value === null || value === '') {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function asJsonText(value, fallback = null) {
  if (value === undefined || value === null) {
    return fallback;
  }

  return JSON.stringify(value);
}

function normalizeEvent(payload) {
  const source = payload && typeof payload === 'object' ? payload : {};
  const normalized = {};

  TEXT_FIELDS.forEach((field) => {
    normalized[field] = asTrimmedText(source[field]);
  });

  normalized.eventId = normalized.eventId || randomUUID();
  normalized.eventType = normalized.eventType || null;
  normalized.occurredAt = normalized.occurredAt || new Date().toISOString();
  normalized.sourceComponent = normalized.sourceComponent || null;
  normalized.httpStatus = asInteger(source.httpStatus);
  normalized.latencyMs = asNumber(source.latencyMs);
  normalized.datasetRowCount = asInteger(source.datasetRowCount);
  normalized.selectedMetrics = asJsonText(Array.isArray(source.selectedMetrics) ? source.selectedMetrics : source.selectedMetrics || null, '[]');
  normalized.benchmarkSummary = asJsonText(source.benchmarkSummary, null);
  normalized.details = asJsonText(source.details, null);
  normalized.rawEvent = asJsonText(source, '{}');

  return normalized;
}

function validateNormalizedEvent(event) {
  const errors = [];

  if (!event.eventType) {
    errors.push('eventType is required');
  } else if (!EVENT_TYPES.has(event.eventType)) {
    errors.push(`Unsupported eventType: ${event.eventType}`);
  }

  if (!event.sourceComponent) {
    errors.push('sourceComponent is required');
  }

  if (!event.occurredAt) {
    errors.push('occurredAt is required');
  }

  return errors;
}

module.exports = {
  EVENT_TYPES,
  normalizeEvent,
  validateNormalizedEvent
};