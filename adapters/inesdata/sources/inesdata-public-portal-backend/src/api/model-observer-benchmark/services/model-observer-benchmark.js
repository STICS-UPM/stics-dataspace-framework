'use strict';

const store = require('../../model-observer-shared/services/model-observer-store');

function getBenchmarkTimeline(benchmarkRunId, query = {}) {
  return store.queryEvents({
    benchmarkRunId,
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
  getBenchmarkTimeline
};