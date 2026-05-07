# Model Clearing House for InesData

## Objective

Design a clearing-house-like capability for AI models inside existing InesData components, without creating a new standalone source or deployable service.

The scope is limited to these components:

- `inesdata-connector`
- `inesdata-connector-interface`
- `inesdata-public-portal-backend`
- `inesdata-public-portal-frontend`
- `inesdata-registration-service`

The target use cases are:

- AI Model Browser
- AI Model Execution
- AI Model Benchmarking
- contract-backed access to federated models
- auditable evidence of what happened, when, by whom, for which model, and under which agreement

## External Research Summary

### Classical IDS Clearing House

The classic IDS definition treats the Clearing House as a trusted logging capability for data-sharing transactions. The main functions repeatedly described in IDSA material are:

- transaction logging
- clearing and settlement
- support for billing
- support for usage-control claim validation
- auditable evidence for contractual steps and data exchange events

Key observations from the reviewed material:

- The IDS RAM describes the Clearing House as an IDS Connector plus a logging service that records information relevant for clearing, billing and usage control.
- The old Dataspace Connector guidance states that finalized contract agreements, data usage events, and artifact request/response events are logged.
- Logged information is correlated by a shared process identifier, typically the contract agreement UUID.
- The specification also states that the Clearing House is implemented on top of a connector, not as an unrelated external pattern.

### Current IDSA Direction: Observer Instead of Clearing House

Recent IDSA material reframes the concept from a dedicated Clearing House into an observability capability.

The important design consequence is this:

- observability does not need a neutral third party
- it can be provided by one participant, both participants, or an independent entity depending on governance
- it is not a plug-in that makes trust appear automatically
- governance, responsibilities, correlation rules, and evidentiary semantics must be defined first

This matches InesData better than trying to recreate a literal IDS Clearing House product.

## Local Findings in InesData

### `inesdata-connector`

There is already reusable audit functionality in the connector.

1. `audit-configuration` logs authenticated management API calls.
2. `audit-event-configuration` subscribes to DSP events and logs contract negotiation and transfer process activity.
3. `model-execution-api` exposes model execution through `/v3/modelexecutions/execute`.

Current evidence already available locally:

- management user identity from bearer token
- local participant ID
- request URI for management calls
- contract negotiation events with counterparty and negotiation ID
- transfer process events with contract ID and asset ID
- model execution control path inside the connector itself

What is missing is not instrumentation from zero. What is missing is:

- structured model-specific evidence
- correlation across browser, agreement, execution, and benchmark flows
- a queryable evidence journal
- UI surfaces to inspect that evidence

### `inesdata-connector-interface`

The connector interface already centralizes the user-facing logic for:

- listing executable and benchmarkable models
- filtering federated models by finalized agreements
- executing models
- benchmarking models on datasets

This makes it the right place to emit user-intent and session-correlation events, but not the authoritative source of truth for actual execution outcomes. Those should be captured in the connector where execution really happens.

### `inesdata-public-portal-backend`

The public portal backend already has:

- a database-backed backend
- custom APIs
- existing catalog proxying logic

This makes it the best place to host a central evidence journal API and storage layer without creating a new service.

### `inesdata-public-portal-frontend`

The public portal frontend already contains catalog browsing surfaces for machine learning assets. It is a natural place to expose read-only evidence views such as:

- model audit timeline
- provider trust and usage summary
- benchmark provenance summary
- agreement-linked execution history

### `inesdata-registration-service`

The registration service already stores participant metadata and exposes it publicly. It should be used as the participant identity registry for evidence enrichment, not as the primary audit ledger.

## Recommended Architecture

### Decision

Implement a **Model Observer / Model Clearing House capability** as a distributed feature with one central evidence journal.

Do **not** build a new standalone service.

Instead:

- capture authoritative events in `inesdata-connector`
- capture user-intent and correlation context in `inesdata-connector-interface`
- persist and query normalized evidence in `inesdata-public-portal-backend`
- visualize evidence in `inesdata-public-portal-frontend`
- enrich participants via `inesdata-registration-service`

### Why this is the best fit

This design matches both the external theory and the current codebase:

- It follows the original IDS idea that the capability is implemented on top of connectors.
- It also follows the newer Observer idea that observability can be distributed and governance-driven.
- It reuses existing audit hooks rather than duplicating runtime control paths.
- It avoids inventing a new source, image, deployment, or operational domain.
- It keeps the connector as the authoritative emitter for contract, transfer, and execution facts.
- It uses the portal backend for storage and query, which is easier than forcing durable evidence storage into connector logs.

## Component Responsibilities

### 1. `inesdata-connector`: authoritative event emission

Extend the existing audit extensions and model execution API so the connector emits structured model evidence events.

Primary responsibilities:

- emit contract and transfer evidence from DSP events
- emit model execution requested/completed/failed events from `model-execution-api`
- attach participant identity and agreement context when available
- send normalized evidence records to the public portal backend
- optionally keep local fallback logging if the journal endpoint is temporarily unavailable

Recommended implementation points:

- extend `audit-event-configuration` so `ContractNegotiationEvent` and `TransferProcessEvent` are converted into structured events, not only `monitor.info(...)` lines
- extend `audit-configuration` so management calls to model execution endpoints can carry correlation metadata
- instrument `ModelExecutionApiController` at `/v3/modelexecutions/execute`

Minimum connector events:

- `CONTRACT_NEGOTIATION_FINALIZED`
- `TRANSFER_PROCESS_STARTED`
- `TRANSFER_PROCESS_COMPLETED`
- `MODEL_EXECUTION_REQUESTED`
- `MODEL_EXECUTION_COMPLETED`
- `MODEL_EXECUTION_FAILED`

Important rule:

The connector must be the source of truth for execution completion, status code, endpoint resolution type, and agreement-derived correlation. The frontend must not be treated as the only proof that execution happened.

### 2. `inesdata-connector-interface`: user intent and benchmark context

Use the connector interface to create correlation IDs and emit user-facing events that explain why a backend action happened.

Primary responsibilities:

- generate a `correlationId` for execution and benchmark flows
- include that `correlationId` in calls to the connector
- emit UI-level evidence for selection and benchmark orchestration
- show model evidence and agreement status inline during execution and benchmarking

Minimum interface events:

- `MODEL_DETAIL_VIEWED`
- `MODEL_SELECTED_FOR_EXECUTION`
- `MODEL_SELECTED_FOR_BENCHMARK`
- `BENCHMARK_STARTED`
- `BENCHMARK_COMPLETED`
- `BENCHMARK_FAILED`

Benchmark-specific note:

Do not log raw validation datasets or full input rows by default. Store:

- dataset fingerprint or hash
- row count
- schema summary
- selected metrics
- aggregated result summary

### 3. `inesdata-public-portal-backend`: central evidence journal

This should host the durable journal and query API.

Primary responsibilities:

- accept evidence records from connector and interface
- normalize them into a shared schema
- persist them in the portal database
- expose query APIs for timelines, filters, and summaries
- enrich events with participant metadata when needed

This backend is the best fit for the journal because it already:

- runs with persistence
- exposes custom APIs
- centralizes catalog-facing information

Recommended backend APIs:

- `POST /api/model-observer/events`
- `POST /api/model-observer/events/bulk`
- `GET /api/model-observer/timeline/:assetId`
- `GET /api/model-observer/agreements/:agreementId`
- `GET /api/model-observer/benchmarks/:benchmarkRunId`
- `GET /api/model-observer/participants/:participantId/summary`

Recommended persistence model:

- `model_observer_event`
- `model_observer_run`
- `model_observer_benchmark`
- `model_observer_event_link`

The exact table names can vary, but the core distinction should remain:

- immutable event rows
- optional derived summary rows for faster UI queries

### 4. `inesdata-public-portal-frontend`: observability UI

Add read-only observability views for machine learning assets.

Recommended screens or panels:

- asset timeline on model detail page
- provider trust summary on catalog item detail
- benchmark provenance panel
- agreement-linked execution history
- per-model evidence badges such as `Agreement-backed`, `Executed`, `Benchmarked`, `Recent failures`

This frontend should remain query-oriented. It should not become the primary writer of authoritative execution facts.

### 5. `inesdata-registration-service`: participant enrichment

Use this service to enrich evidence with participant information such as:

- `participantId`
- public URL
- shared vocabulary URL
- display metadata added later if needed

Recommended role:

- reference source for provider/consumer identity
- lookup service during journal enrichment

Not recommended:

- using it as the main event ledger
- coupling model evidence persistence to participant CRUD transactions

## Evidence Model

### Core event schema

Every evidence record should include at least:

- `eventId`
- `eventType`
- `occurredAt`
- `sourceComponent`
- `participantId`
- `actorType` (`user`, `connector`, `system`)
- `actorId`
- `correlationId`
- `processId`
- `assetId`
- `assetType`
- `agreementId`
- `negotiationId`
- `transferProcessId`
- `benchmarkRunId`
- `status`
- `details`
- `payloadHash`
- `responseHash`

### Model-specific fields

For model events, add:

- `modelName`
- `providerParticipantId`
- `consumerParticipantId`
- `executionMode` (`local`, `federated-with-agreement`)
- `endpointKind` (`local-http`, `edr-http`)
- `httpStatus`
- `latencyMs`
- `taskType`
- `selectedMetrics`
- `datasetFingerprint`
- `datasetRowCount`
- `benchmarkSummary`

### Privacy rule

Do not persist full raw inputs, raw outputs, or raw datasets by default.

Persist instead:

- hashes
- counts
- schema summaries
- bounded previews when explicitly allowed
- aggregated benchmark metrics

This is especially important because model inputs may contain confidential or personal data.

## Correlation Strategy

The most important design choice is correlation.

### Primary identifiers

- `agreementId` should be the primary cross-connector process identifier when a federated model is used
- `correlationId` should be created by the UI for one user action or benchmark run
- `benchmarkRunId` should group all benchmark events for one benchmark execution
- `transferProcessId` should link execution to EDR establishment when federation is involved

### Recommended rules

1. For local models, use `correlationId` plus `assetId` as the main grouping key.
2. For federated models, use `agreementId` as the main external process key.
3. For benchmarks, generate one `benchmarkRunId` and attach child execution events for each model.
4. When possible, include both `correlationId` and `agreementId`; they answer different questions.

## Event Flows

### A. Model Browser

1. Public portal frontend loads model details.
2. Public portal backend serves catalog data.
3. Frontend or backend emits `MODEL_DETAIL_VIEWED`.
4. If the asset is federated, the timeline also shows whether a finalized agreement exists.

### B. Model Execution

1. Connector interface generates `correlationId`.
2. User selects a model.
3. Connector interface calls `/v3/modelexecutions/execute` with `assetId`, payload and `correlationId`.
4. Connector resolves local or federated execution target.
5. If federated, connector resolves `agreementId`, starts transfer, resolves EDR, then invokes endpoint.
6. Connector emits structured evidence for request, transfer linkage and completion.
7. Portal backend stores immutable evidence.
8. Frontend can query the timeline later.

### C. Benchmarking

1. Connector interface creates `benchmarkRunId` and `correlationId`.
2. Each model execution inside the benchmark carries the same `benchmarkRunId` and a per-call child identifier.
3. Connector emits execution-level evidence.
4. Connector interface emits benchmark orchestration events and summary metrics.
5. Portal backend stores both detailed and summarized evidence.
6. Public portal frontend can later show benchmark provenance and comparison history.

## Best Implementation Sequence

### Phase 1. Structured evidence foundation

Implement first:

- normalized event schema
- event ingestion API in public portal backend
- connector-side structured emission for DSP and model execution events
- correlation ID propagation from connector interface to connector

This phase gives the system real evidence without changing user flows much.

### Phase 2. Query and visualization

Implement next:

- timeline APIs
- model detail evidence panels in public portal frontend
- execution and benchmark evidence panels in connector interface

### Phase 3. Derived trust summaries

Implement later:

- per-provider reliability summaries
- recent execution failure ratios
- agreement-backed usage summaries
- benchmark provenance digests

## What Should Not Be Done

- Do not create a sixth standalone service just for the clearing house.
- Do not rely only on frontend logs as evidence of execution.
- Do not store full datasets and raw payloads by default.
- Do not use plain text logs as the only durable journal.
- Do not couple the evidence ledger to participant CRUD.

## Concrete Recommendation

The best implementation for InesData is **not** a literal classic Clearing House service.

The best implementation is a **Model Observer capability** composed of:

- authoritative event capture in `inesdata-connector`
- correlation and benchmark context in `inesdata-connector-interface`
- durable journal and query API in `inesdata-public-portal-backend`
- evidence visualization in `inesdata-public-portal-frontend`
- participant enrichment from `inesdata-registration-service`

This gives InesData the practical benefits expected from a clearing-house-like role for models:

- accountability
- traceability
- agreement-aware evidence
- benchmark provenance
- provider and consumer observability

without introducing a new source or breaking the current component model.

## Source Material Used

- IDSA RAM 4, section on Clearing House
- IDSA Clearing House specification metadata at Zenodo
- Dataspace Connector communication guide for IDS Clearing House
- IDSA article on the shift from Clearing House to Observer
- current InesData code in connector audit extensions, model execution API, connector interface, public portal backend/frontend, and registration service