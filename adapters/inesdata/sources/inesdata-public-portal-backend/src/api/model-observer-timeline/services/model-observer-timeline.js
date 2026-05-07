'use strict';

const store = require('../../model-observer-shared/services/model-observer-store');

function getTimeline(assetId, query = {}) {
  return store.queryEvents({
    assetId,
    agreementId: query.agreementId,
    participantId: query.participantId,
    correlationId: query.correlationId,
    eventType: query.eventType,
    status: query.status,
    from: query.from,
    to: query.to
  }, {
    limit: query.limit,
    offset: query.offset
  });
}

module.exports = {
  getTimeline
};