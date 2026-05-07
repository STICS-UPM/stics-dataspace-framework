'use strict';

const assert = require('node:assert/strict');
const fs = require('fs');

const eventService = require('../src/api/model-observer-event/services/model-observer-event');
const timelineService = require('../src/api/model-observer-timeline/services/model-observer-timeline');
const agreementService = require('../src/api/model-observer-agreement/services/model-observer-agreement');
const benchmarkService = require('../src/api/model-observer-benchmark/services/model-observer-benchmark');
const summaryService = require('../src/api/model-observer-summary/services/model-observer-summary');
const store = require('../src/api/model-observer-shared/services/model-observer-store');

function deleteIfExists(targetPath) {
  if (fs.existsSync(targetPath)) {
    fs.rmSync(targetPath, { force: true });
  }
}

function resolveFallbackJsonPath(dbPath) {
  return dbPath.endsWith('.db') ? `${dbPath.slice(0, -3)}.json` : `${dbPath}.json`;
}

function main() {
  const dbPath = store.resolveDbFilePath();
  const jsonPath = resolveFallbackJsonPath(dbPath);

  deleteIfExists(dbPath);
  deleteIfExists(jsonPath);

  const baseEvent = {
    sourceComponent: 'model-observer-smoke-test',
    assetId: 'asset-smoke-1',
    agreementId: 'agreement-smoke-1',
    benchmarkRunId: 'benchmark-smoke-1',
    participantId: 'connector-c1',
    modelName: 'Smoke Model'
  };

  const inserted = [
    eventService.createEvent({ ...baseEvent, eventId: 'evt-1', eventType: 'MODEL_DETAIL_VIEWED', status: 'VIEWED' }),
    eventService.createEvent({ ...baseEvent, eventId: 'evt-2', eventType: 'BENCHMARK_STARTED', status: 'STARTED', selectedMetrics: ['Accuracy'] }),
    eventService.createEvent({ ...baseEvent, eventId: 'evt-3', eventType: 'MODEL_EXECUTION_COMPLETED', status: 'COMPLETED', httpStatus: 200, latencyMs: 123 })
  ];

  const timeline = timelineService.getTimeline(baseEvent.assetId, {});
  const agreement = agreementService.getAgreementTimeline(baseEvent.agreementId, {});
  const benchmark = benchmarkService.getBenchmarkTimeline(baseEvent.benchmarkRunId, {});
  const summary = summaryService.getParticipantSummary(baseEvent.participantId);

  assert.equal(inserted.length, 3);
  assert.ok(inserted.every((item) => item.inserted === true));
  assert.equal(timeline.total, 3);
  assert.equal(agreement.total, 3);
  assert.equal(benchmark.total, 3);
  assert.equal(summary.recentFailures, 0);
  assert.deepEqual(
    Object.keys(summary.totalsByEventType).sort(),
    ['BENCHMARK_STARTED', 'MODEL_DETAIL_VIEWED', 'MODEL_EXECUTION_COMPLETED']
  );

  console.log(JSON.stringify({
    ok: true,
    storageMode: fs.existsSync(jsonPath) ? 'json-fallback' : 'sqlite',
    timelineTypes: timeline.items.map((item) => item.eventType),
    summaryTypes: Object.keys(summary.totalsByEventType).sort()
  }, null, 2));
}

try {
  main();
} catch (error) {
  console.error(error);
  process.exitCode = 1;
}