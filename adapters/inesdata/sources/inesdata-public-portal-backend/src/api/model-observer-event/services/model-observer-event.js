'use strict';

const store = require('../../model-observer-shared/services/model-observer-store');
const validator = require('../../model-observer-shared/services/model-observer-validator');

function createEvent(payload) {
  const normalized = validator.normalizeEvent(payload);
  const errors = validator.validateNormalizedEvent(normalized);
  if (errors.length > 0) {
    const error = new Error('Invalid model observer event');
    error.validationErrors = errors;
    throw error;
  }

  const result = store.insertEvent(normalized);
  return {
    eventId: normalized.eventId,
    inserted: result.changes > 0
  };
}

function createBulkEvents(payloads) {
  if (!Array.isArray(payloads)) {
    const error = new Error('Body must be an array of events');
    error.validationErrors = ['Body must be an array of events'];
    throw error;
  }

  const normalizedBatch = payloads.map(validator.normalizeEvent);
  const validationErrors = normalizedBatch
    .map((event, index) => ({ index, errors: validator.validateNormalizedEvent(event) }))
    .filter((entry) => entry.errors.length > 0);

  if (validationErrors.length > 0) {
    const error = new Error('Invalid model observer event batch');
    error.validationErrors = validationErrors;
    throw error;
  }

  const results = store.insertEvents(normalizedBatch);
  const inserted = results.filter((result) => result.changes > 0).length;

  return {
    total: normalizedBatch.length,
    inserted,
    ignored: normalizedBatch.length - inserted,
    eventIds: normalizedBatch.map((event) => event.eventId)
  };
}

module.exports = {
  createEvent,
  createBulkEvents
};