'use strict';

const fs = require('fs');
const path = require('path');

let Database = null;
try {
  Database = require('better-sqlite3');
} catch (error) {
  Database = null;
}

const DB_FILE = process.env.MODEL_OBSERVER_DB_FILENAME || '.tmp/model-observer.db';

let db;

function resolveJsonFilePath() {
  const dbFilePath = resolveDbFilePath();
  if (dbFilePath.endsWith('.db')) {
    return `${dbFilePath.slice(0, -3)}.json`;
  }
  return `${dbFilePath}.json`;
}

function resolveDbFilePath() {
  return path.resolve(process.cwd(), DB_FILE);
}

function ensureDatabase() {
  if (!Database) {
    return null;
  }

  if (db) {
    return db;
  }

  try {
    const dbFilePath = resolveDbFilePath();
    fs.mkdirSync(path.dirname(dbFilePath), { recursive: true });
    db = new Database(dbFilePath);
    db.pragma('journal_mode = WAL');

    db.exec(`
      CREATE TABLE IF NOT EXISTS model_observer_event (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        source_component TEXT NOT NULL,
        participant_id TEXT,
        actor_type TEXT,
        actor_id TEXT,
        correlation_id TEXT,
        process_id TEXT,
        asset_id TEXT,
        agreement_id TEXT,
        negotiation_id TEXT,
        transfer_process_id TEXT,
        benchmark_run_id TEXT,
        status TEXT,
        model_name TEXT,
        provider_participant_id TEXT,
        consumer_participant_id TEXT,
        execution_mode TEXT,
        endpoint_kind TEXT,
        http_status INTEGER,
        latency_ms REAL,
        task_type TEXT,
        dataset_fingerprint TEXT,
        dataset_row_count INTEGER,
        selected_metrics TEXT,
        benchmark_summary TEXT,
        details TEXT,
        payload_hash TEXT,
        response_hash TEXT,
        raw_event TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );

      CREATE INDEX IF NOT EXISTS idx_model_observer_asset_id ON model_observer_event(asset_id);
      CREATE INDEX IF NOT EXISTS idx_model_observer_agreement_id ON model_observer_event(agreement_id);
      CREATE INDEX IF NOT EXISTS idx_model_observer_benchmark_run_id ON model_observer_event(benchmark_run_id);
      CREATE INDEX IF NOT EXISTS idx_model_observer_participant_id ON model_observer_event(participant_id);
      CREATE INDEX IF NOT EXISTS idx_model_observer_occurred_at ON model_observer_event(occurred_at DESC);
      CREATE INDEX IF NOT EXISTS idx_model_observer_event_type ON model_observer_event(event_type);
    `);

    return db;
  } catch (error) {
    Database = null;
    db = null;
    return null;
  }
}

function readJsonEvents() {
  const jsonFilePath = resolveJsonFilePath();
  fs.mkdirSync(path.dirname(jsonFilePath), { recursive: true });
  if (!fs.existsSync(jsonFilePath)) {
    fs.writeFileSync(jsonFilePath, JSON.stringify({ events: [] }, null, 2));
  }

  const content = fs.readFileSync(jsonFilePath, 'utf8');
  const parsed = JSON.parse(content || '{}');
  return Array.isArray(parsed.events) ? parsed.events : [];
}

function writeJsonEvents(events) {
  const jsonFilePath = resolveJsonFilePath();
  fs.mkdirSync(path.dirname(jsonFilePath), { recursive: true });
  fs.writeFileSync(jsonFilePath, JSON.stringify({ events }, null, 2));
}

function mapRow(row) {
  if (!row) {
    return null;
  }

  return {
    eventId: row.event_id,
    eventType: row.event_type,
    occurredAt: row.occurred_at,
    sourceComponent: row.source_component,
    participantId: row.participant_id,
    actorType: row.actor_type,
    actorId: row.actor_id,
    correlationId: row.correlation_id,
    processId: row.process_id,
    assetId: row.asset_id,
    agreementId: row.agreement_id,
    negotiationId: row.negotiation_id,
    transferProcessId: row.transfer_process_id,
    benchmarkRunId: row.benchmark_run_id,
    status: row.status,
    modelName: row.model_name,
    providerParticipantId: row.provider_participant_id,
    consumerParticipantId: row.consumer_participant_id,
    executionMode: row.execution_mode,
    endpointKind: row.endpoint_kind,
    httpStatus: row.http_status,
    latencyMs: row.latency_ms,
    taskType: row.task_type,
    datasetFingerprint: row.dataset_fingerprint,
    datasetRowCount: row.dataset_row_count,
    selectedMetrics: row.selected_metrics ? JSON.parse(row.selected_metrics) : [],
    benchmarkSummary: row.benchmark_summary ? JSON.parse(row.benchmark_summary) : null,
    details: row.details ? JSON.parse(row.details) : null,
    payloadHash: row.payload_hash,
    responseHash: row.response_hash,
    rawEvent: row.raw_event ? JSON.parse(row.raw_event) : null,
    createdAt: row.created_at
  };
}

function buildWhereClause(filters = {}) {
  const clauses = [];
  const params = {};

  const equalsFilters = {
    assetId: 'asset_id',
    agreementId: 'agreement_id',
    benchmarkRunId: 'benchmark_run_id',
    participantId: 'participant_id',
    correlationId: 'correlation_id',
    eventType: 'event_type',
    status: 'status'
  };

  Object.entries(equalsFilters).forEach(([key, column]) => {
    if (filters[key]) {
      clauses.push(`${column} = @${key}`);
      params[key] = filters[key];
    }
  });

  if (filters.from) {
    clauses.push('occurred_at >= @from');
    params.from = filters.from;
  }

  if (filters.to) {
    clauses.push('occurred_at <= @to');
    params.to = filters.to;
  }

  return {
    sql: clauses.length > 0 ? `WHERE ${clauses.join(' AND ')}` : '',
    params
  };
}

function insertEvent(event) {
  const connection = ensureDatabase();
  if (!connection) {
    const events = readJsonEvents();
    const existing = events.find((item) => item.event_id === event.eventId);
    if (existing) {
      return { changes: 0 };
    }

    events.push({
      event_id: event.eventId,
      event_type: event.eventType,
      occurred_at: event.occurredAt,
      source_component: event.sourceComponent,
      participant_id: event.participantId,
      actor_type: event.actorType,
      actor_id: event.actorId,
      correlation_id: event.correlationId,
      process_id: event.processId,
      asset_id: event.assetId,
      agreement_id: event.agreementId,
      negotiation_id: event.negotiationId,
      transfer_process_id: event.transferProcessId,
      benchmark_run_id: event.benchmarkRunId,
      status: event.status,
      model_name: event.modelName,
      provider_participant_id: event.providerParticipantId,
      consumer_participant_id: event.consumerParticipantId,
      execution_mode: event.executionMode,
      endpoint_kind: event.endpointKind,
      http_status: event.httpStatus,
      latency_ms: event.latencyMs,
      task_type: event.taskType,
      dataset_fingerprint: event.datasetFingerprint,
      dataset_row_count: event.datasetRowCount,
      selected_metrics: event.selectedMetrics,
      benchmark_summary: event.benchmarkSummary,
      details: event.details,
      payload_hash: event.payloadHash,
      response_hash: event.responseHash,
      raw_event: event.rawEvent,
      created_at: new Date().toISOString()
    });
    writeJsonEvents(events);
    return { changes: 1 };
  }

  const statement = connection.prepare(`
    INSERT OR IGNORE INTO model_observer_event (
      event_id, event_type, occurred_at, source_component, participant_id, actor_type, actor_id,
      correlation_id, process_id, asset_id, agreement_id, negotiation_id, transfer_process_id,
      benchmark_run_id, status, model_name, provider_participant_id, consumer_participant_id,
      execution_mode, endpoint_kind, http_status, latency_ms, task_type, dataset_fingerprint,
      dataset_row_count, selected_metrics, benchmark_summary, details, payload_hash,
      response_hash, raw_event
    ) VALUES (
      @eventId, @eventType, @occurredAt, @sourceComponent, @participantId, @actorType, @actorId,
      @correlationId, @processId, @assetId, @agreementId, @negotiationId, @transferProcessId,
      @benchmarkRunId, @status, @modelName, @providerParticipantId, @consumerParticipantId,
      @executionMode, @endpointKind, @httpStatus, @latencyMs, @taskType, @datasetFingerprint,
      @datasetRowCount, @selectedMetrics, @benchmarkSummary, @details, @payloadHash,
      @responseHash, @rawEvent
    )
  `);

  return statement.run(event);
}

function insertEvents(events) {
  const connection = ensureDatabase();
  if (!connection) {
    return events.map((event) => insertEvent(event));
  }

  const transaction = connection.transaction((batch) => {
    return batch.map((event) => insertEvent(event));
  });

  return transaction(events);
}

function queryEvents(filters = {}, options = {}) {
  const connection = ensureDatabase();
  const limit = Number.isFinite(Number(options.limit)) ? Math.max(1, Number(options.limit)) : 100;
  const offset = Number.isFinite(Number(options.offset)) ? Math.max(0, Number(options.offset)) : 0;
  const { sql, params } = buildWhereClause(filters);

  if (!connection) {
    const items = readJsonEvents()
      .filter((item) => {
        if (filters.assetId && item.asset_id !== filters.assetId) {
          return false;
        }
        if (filters.agreementId && item.agreement_id !== filters.agreementId) {
          return false;
        }
        if (filters.benchmarkRunId && item.benchmark_run_id !== filters.benchmarkRunId) {
          return false;
        }
        if (filters.participantId && item.participant_id !== filters.participantId) {
          return false;
        }
        if (filters.correlationId && item.correlation_id !== filters.correlationId) {
          return false;
        }
        if (filters.eventType && item.event_type !== filters.eventType) {
          return false;
        }
        if (filters.status && item.status !== filters.status) {
          return false;
        }
        if (filters.from && item.occurred_at < filters.from) {
          return false;
        }
        if (filters.to && item.occurred_at > filters.to) {
          return false;
        }
        return true;
      })
      .sort((left, right) => {
        if (left.occurred_at === right.occurred_at) {
          return `${right.created_at}`.localeCompare(`${left.created_at}`);
        }
        return `${right.occurred_at}`.localeCompare(`${left.occurred_at}`);
      });

    return {
      items: items.slice(offset, offset + limit).map(mapRow),
      total: items.length,
      limit,
      offset
    };
  }

  const rows = connection.prepare(`
    SELECT *
    FROM model_observer_event
    ${sql}
    ORDER BY occurred_at DESC, created_at DESC
    LIMIT @limit OFFSET @offset
  `).all({ ...params, limit, offset });

  const totalRow = connection.prepare(`
    SELECT COUNT(*) AS total
    FROM model_observer_event
    ${sql}
  `).get(params);

  return {
    items: rows.map(mapRow),
    total: totalRow ? totalRow.total : 0,
    limit,
    offset
  };
}

function participantSummary(participantId) {
  const connection = ensureDatabase();
  if (!connection) {
    const filtered = readJsonEvents().filter((item) => item.participant_id === participantId);
    const latest = [...filtered].sort((left, right) => `${right.occurred_at}`.localeCompare(`${left.occurred_at}`))[0];
    const totalsByEventType = filtered.reduce((acc, item) => {
      acc[item.event_type] = (acc[item.event_type] || 0) + 1;
      return acc;
    }, {});
    const recentFailures = filtered.filter((item) => ['failed', 'error', 'FAILED', 'ERROR'].includes(item.status)).length;

    return {
      participantId,
      totalsByEventType,
      recentFailures,
      latestEvent: mapRow(latest)
    };
  }

  const totals = connection.prepare(`
    SELECT event_type, COUNT(*) AS total
    FROM model_observer_event
    WHERE participant_id = ?
    GROUP BY event_type
  `).all(participantId);

  const latestEvent = connection.prepare(`
    SELECT *
    FROM model_observer_event
    WHERE participant_id = ?
    ORDER BY occurred_at DESC, created_at DESC
    LIMIT 1
  `).get(participantId);

  const recentFailures = connection.prepare(`
    SELECT COUNT(*) AS total
    FROM model_observer_event
    WHERE participant_id = ?
      AND status IN ('failed', 'error', 'FAILED', 'ERROR')
  `).get(participantId);

  return {
    participantId,
    totalsByEventType: totals.reduce((acc, row) => {
      acc[row.event_type] = row.total;
      return acc;
    }, {}),
    recentFailures: recentFailures ? recentFailures.total : 0,
    latestEvent: mapRow(latestEvent)
  };
}

module.exports = {
  resolveDbFilePath,
  insertEvent,
  insertEvents,
  queryEvents,
  participantSummary
};