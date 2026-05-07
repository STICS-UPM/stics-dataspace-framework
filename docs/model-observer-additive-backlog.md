# Model Observer Additive-Only Backlog

## Scope

This backlog assumes a strict additive strategy:

- do not modify existing files inside InesData components
- only add new files, new modules, new pages, new extensions, new endpoints, and new persistence artifacts
- keep the first implementation isolated from current execution, catalog, benchmark, and registration flows

The goal is to introduce a model-focused observability capability without risking regressions in what is already implemented.

## Delivery Strategy

### Phase 1

Create the journal backend and the first read-only observability UI.

### Phase 2

Add connector-side observer extensions that emit contract and transfer evidence.

### Phase 3

Add optional connector-interface observability pages and benchmark provenance views.

## Backlog by Component

## 1. `inesdata-public-portal-backend`

### Objective

Create the durable event journal and query API as a new bounded context.

### New folders to create

- `src/api/model-observer-event/`
- `src/api/model-observer-timeline/`
- `src/api/model-observer-summary/`
- `src/api/model-observer-agreement/`
- `src/api/model-observer-benchmark/`
- `src/components/model-observer/`
- `database/migrations/model-observer/`

### New files to create

#### Event ingestion API

- `src/api/model-observer-event/controllers/model-observer-event.js`
- `src/api/model-observer-event/routes/model-observer-event.js`
- `src/api/model-observer-event/services/model-observer-event.js`

Purpose:

- ingest single structured evidence records
- validate minimal schema
- write immutable journal rows

#### Bulk ingestion API

- `src/api/model-observer-event/controllers/model-observer-bulk-event.js`
- `src/api/model-observer-event/routes/model-observer-bulk-event.js`
- `src/api/model-observer-event/services/model-observer-bulk-event.js`

Purpose:

- receive batched events from connector extensions
- support retry-safe idempotent ingestion

#### Timeline query API

- `src/api/model-observer-timeline/controllers/model-observer-timeline.js`
- `src/api/model-observer-timeline/routes/model-observer-timeline.js`
- `src/api/model-observer-timeline/services/model-observer-timeline.js`

Purpose:

- return timeline by `assetId`
- support filters by event type, date range, participant, agreement

#### Agreement query API

- `src/api/model-observer-agreement/controllers/model-observer-agreement.js`
- `src/api/model-observer-agreement/routes/model-observer-agreement.js`
- `src/api/model-observer-agreement/services/model-observer-agreement.js`

Purpose:

- return all events linked to one `agreementId`
- expose provider/consumer correlation view

#### Benchmark query API

- `src/api/model-observer-benchmark/controllers/model-observer-benchmark.js`
- `src/api/model-observer-benchmark/routes/model-observer-benchmark.js`
- `src/api/model-observer-benchmark/services/model-observer-benchmark.js`

Purpose:

- return benchmark runs and summaries by `benchmarkRunId`
- expose per-model comparison metadata

#### Participant summary API

- `src/api/model-observer-summary/controllers/model-observer-summary.js`
- `src/api/model-observer-summary/routes/model-observer-summary.js`
- `src/api/model-observer-summary/services/model-observer-summary.js`

Purpose:

- aggregate counts and recent status by `participantId`
- support provider and consumer observability views

#### Shared model-observer utilities

- `src/components/model-observer/event-schema.json`
- `src/components/model-observer/event-types.json`
- `src/components/model-observer/model-observer-query-builder.js`
- `src/components/model-observer/model-observer-normalizer.js`
- `src/components/model-observer/model-observer-idempotency.js`
- `src/components/model-observer/model-observer-registration-enricher.js`

Purpose:

- keep all observer-specific logic separate from current catalog code

#### Database artifacts

- `database/migrations/model-observer/001_create_model_observer_event.sql`
- `database/migrations/model-observer/002_create_model_observer_run.sql`
- `database/migrations/model-observer/003_create_model_observer_benchmark.sql`
- `database/migrations/model-observer/004_create_model_observer_projection.sql`
- `database/migrations/model-observer/005_create_model_observer_indexes.sql`

Purpose:

- create journal tables without altering existing data model

### Functional endpoints to expose

- `POST /api/model-observer/events`
- `POST /api/model-observer/events/bulk`
- `GET /api/model-observer/timeline/:assetId`
- `GET /api/model-observer/agreements/:agreementId`
- `GET /api/model-observer/benchmarks/:benchmarkRunId`
- `GET /api/model-observer/participants/:participantId/summary`

### Acceptance criteria

- journal storage is isolated from current portal APIs
- event ingestion is idempotent
- timeline queries work without touching current catalog endpoints
- participant enrichment is optional and decoupled

## 2. `inesdata-public-portal-frontend`

### Objective

Add a new observability section as new pages and new services only.

### New folders to create

- `src/app/pages/model-observer/`
- `src/app/pages/model-observer/model-observer-home/`
- `src/app/pages/model-observer/model-observer-timeline/`
- `src/app/pages/model-observer/model-observer-agreement/`
- `src/app/pages/model-observer/model-observer-benchmark-history/`
- `src/app/pages/model-observer/model-observer-participant-summary/`
- `src/app/shared/services/model-observer/`
- `src/app/shared/models/model-observer/`
- `src/app/shared/components/model-observer/`

### New files to create

#### Module and routing

- `src/app/pages/model-observer/model-observer.module.ts`
- `src/app/pages/model-observer/model-observer-routing.module.ts`

Purpose:

- isolate routes and declarations for the new feature

#### Pages

- `src/app/pages/model-observer/model-observer-home/model-observer-home.component.ts`
- `src/app/pages/model-observer/model-observer-home/model-observer-home.component.html`
- `src/app/pages/model-observer/model-observer-home/model-observer-home.component.scss`
- `src/app/pages/model-observer/model-observer-timeline/model-observer-timeline.component.ts`
- `src/app/pages/model-observer/model-observer-timeline/model-observer-timeline.component.html`
- `src/app/pages/model-observer/model-observer-timeline/model-observer-timeline.component.scss`
- `src/app/pages/model-observer/model-observer-agreement/model-observer-agreement.component.ts`
- `src/app/pages/model-observer/model-observer-agreement/model-observer-agreement.component.html`
- `src/app/pages/model-observer/model-observer-agreement/model-observer-agreement.component.scss`
- `src/app/pages/model-observer/model-observer-benchmark-history/model-observer-benchmark-history.component.ts`
- `src/app/pages/model-observer/model-observer-benchmark-history/model-observer-benchmark-history.component.html`
- `src/app/pages/model-observer/model-observer-benchmark-history/model-observer-benchmark-history.component.scss`
- `src/app/pages/model-observer/model-observer-participant-summary/model-observer-participant-summary.component.ts`
- `src/app/pages/model-observer/model-observer-participant-summary/model-observer-participant-summary.component.html`
- `src/app/pages/model-observer/model-observer-participant-summary/model-observer-participant-summary.component.scss`

Purpose:

- provide a separate observer experience without modifying current catalog pages

#### Services

- `src/app/shared/services/model-observer/model-observer-api.service.ts`
- `src/app/shared/services/model-observer/model-observer-timeline.service.ts`
- `src/app/shared/services/model-observer/model-observer-summary.service.ts`
- `src/app/shared/services/model-observer/model-observer-benchmark.service.ts`

Purpose:

- centralize calls to the new journal APIs

#### Models

- `src/app/shared/models/model-observer/model-observer-event.model.ts`
- `src/app/shared/models/model-observer/model-observer-timeline.model.ts`
- `src/app/shared/models/model-observer/model-observer-summary.model.ts`
- `src/app/shared/models/model-observer/model-observer-benchmark.model.ts`
- `src/app/shared/models/model-observer/model-observer-filter.model.ts`

Purpose:

- keep typed observer data separate from existing catalog models

#### Reusable UI components

- `src/app/shared/components/model-observer/model-event-card/model-event-card.component.ts`
- `src/app/shared/components/model-observer/model-event-card/model-event-card.component.html`
- `src/app/shared/components/model-observer/model-event-card/model-event-card.component.scss`
- `src/app/shared/components/model-observer/model-timeline-filter/model-timeline-filter.component.ts`
- `src/app/shared/components/model-observer/model-timeline-filter/model-timeline-filter.component.html`
- `src/app/shared/components/model-observer/model-timeline-filter/model-timeline-filter.component.scss`
- `src/app/shared/components/model-observer/model-observer-badge/model-observer-badge.component.ts`
- `src/app/shared/components/model-observer/model-observer-badge/model-observer-badge.component.html`
- `src/app/shared/components/model-observer/model-observer-badge/model-observer-badge.component.scss`

Purpose:

- build the UI as independent components that do not alter current pages

### Functional views to deliver first

1. Timeline by `assetId`
2. Agreement evidence by `agreementId`
3. Benchmark history by `benchmarkRunId`
4. Participant summary by `participantId`

### Acceptance criteria

- no changes to current catalog and home pages are required for first delivery
- all observer UI routes are isolated in a new module
- observer UI consumes only new backend APIs

## 3. `inesdata-connector`

### Objective

Add new extensions for observability using only new extension folders and new classes.

### New extension folders to create

- `extensions/model-observer-dsp-events/`
- `extensions/model-observer-journal-client/`
- `extensions/model-observer-management-observer/`

### New files to create

#### DSP event observer extension

- `extensions/model-observer-dsp-events/src/main/java/org/upm/inesdata/modelobserver/dsp/ModelObserverDspEventExtension.java`
- `extensions/model-observer-dsp-events/src/main/java/org/upm/inesdata/modelobserver/dsp/ModelObserverDspEventSubscriber.java`
- `extensions/model-observer-dsp-events/src/main/java/org/upm/inesdata/modelobserver/dsp/ModelObserverDspEventMapper.java`
- `extensions/model-observer-dsp-events/src/main/resources/model-observer-dsp-events.properties`
- `extensions/model-observer-dsp-events/README.md`
- `extensions/model-observer-dsp-events/build.gradle`

Purpose:

- subscribe to `ContractNegotiationEvent`
- subscribe to `TransferProcessEvent`
- transform them into normalized model-observer records

#### Journal client extension

- `extensions/model-observer-journal-client/src/main/java/org/upm/inesdata/modelobserver/client/ModelObserverJournalClient.java`
- `extensions/model-observer-journal-client/src/main/java/org/upm/inesdata/modelobserver/client/ModelObserverJournalConfig.java`
- `extensions/model-observer-journal-client/src/main/java/org/upm/inesdata/modelobserver/client/ModelObserverRetryPolicy.java`
- `extensions/model-observer-journal-client/src/main/java/org/upm/inesdata/modelobserver/client/ModelObserverEventEnvelope.java`
- `extensions/model-observer-journal-client/src/main/resources/model-observer-journal-client.properties`
- `extensions/model-observer-journal-client/README.md`
- `extensions/model-observer-journal-client/build.gradle`

Purpose:

- send normalized events to the portal backend journal
- support retries and non-blocking fallback logging

#### Management API observer extension

- `extensions/model-observer-management-observer/src/main/java/org/upm/inesdata/modelobserver/management/ModelObserverManagementExtension.java`
- `extensions/model-observer-management-observer/src/main/java/org/upm/inesdata/modelobserver/management/ModelObserverManagementFilter.java`
- `extensions/model-observer-management-observer/src/main/java/org/upm/inesdata/modelobserver/management/ModelObserverManagementEventMapper.java`
- `extensions/model-observer-management-observer/src/main/resources/model-observer-management-observer.properties`
- `extensions/model-observer-management-observer/README.md`
- `extensions/model-observer-management-observer/build.gradle`

Purpose:

- observe management calls without altering current audit filter files
- capture request metadata where possible

### Important implementation limit

Under the additive-only rule, direct instrumentation of the existing model execution controller should not be assumed in phase 1.

That means:

- phase 1 connector observability should focus on DSP and management-level evidence
- model execution completion evidence should be added only if it can be observed through a new filter, interceptor, or event extension without editing the current controller

### Acceptance criteria

- all observer behavior is deployed as new extensions only
- existing audit extensions remain untouched
- failure to send journal events does not block business flows

## 4. `inesdata-connector-interface`

### Objective

Add optional observability views as new pages and new services, without touching current execution and benchmark pages.

### New folders to create

- `src/app/pages/model-observer/`
- `src/app/pages/model-observer/model-observer-dashboard/`
- `src/app/pages/model-observer/model-observer-run-detail/`
- `src/app/pages/model-observer/model-observer-benchmark-detail/`
- `src/app/shared/services/model-observer/`
- `src/app/shared/models/model-observer/`

### New files to create

#### Module and routing

- `src/app/pages/model-observer/model-observer.module.ts`
- `src/app/pages/model-observer/model-observer-routing.module.ts`

#### Pages

- `src/app/pages/model-observer/model-observer-dashboard/model-observer-dashboard.component.ts`
- `src/app/pages/model-observer/model-observer-dashboard/model-observer-dashboard.component.html`
- `src/app/pages/model-observer/model-observer-dashboard/model-observer-dashboard.component.scss`
- `src/app/pages/model-observer/model-observer-run-detail/model-observer-run-detail.component.ts`
- `src/app/pages/model-observer/model-observer-run-detail/model-observer-run-detail.component.html`
- `src/app/pages/model-observer/model-observer-run-detail/model-observer-run-detail.component.scss`
- `src/app/pages/model-observer/model-observer-benchmark-detail/model-observer-benchmark-detail.component.ts`
- `src/app/pages/model-observer/model-observer-benchmark-detail/model-observer-benchmark-detail.component.html`
- `src/app/pages/model-observer/model-observer-benchmark-detail/model-observer-benchmark-detail.component.scss`

#### Services

- `src/app/shared/services/model-observer/model-observer-api.service.ts`
- `src/app/shared/services/model-observer/model-observer-run.service.ts`
- `src/app/shared/services/model-observer/model-observer-benchmark.service.ts`

#### Models

- `src/app/shared/models/model-observer/model-observer-run.model.ts`
- `src/app/shared/models/model-observer/model-observer-benchmark-detail.model.ts`
- `src/app/shared/models/model-observer/model-observer-event.model.ts`

### Functional purpose

- provide operational observability pages for model execution and benchmark evidence
- keep current AI execution and benchmarking pages unchanged

### Acceptance criteria

- observer pages are new routes only
- current model execution and benchmark pages are not edited
- if additive route registration is not feasible, this component can be deferred to a later phase

## 5. `inesdata-registration-service`

### Objective

Use as-is for enrichment and avoid first-phase changes.

### New files to create

No new files are required in phase 1.

### Optional phase-3 additions only if needed

- `src/main/java/org/upm/inesdata/registration_service/dto/ParticipantObserverProfile.java`
- `src/main/java/org/upm/inesdata/registration_service/controller/ParticipantObserverProfileController.java`
- `src/main/java/org/upm/inesdata/registration_service/service/ParticipantObserverProfileService.java`

Purpose:

- expose observer-oriented participant metadata without changing existing participant contracts

### Recommendation

Do not start here.

Use existing participant endpoints from the new portal-backend enricher first.

## Cross-Component Event Model

### Files to define centrally in documentation and then mirror in implementations

- `eventId`
- `eventType`
- `occurredAt`
- `sourceComponent`
- `participantId`
- `actorType`
- `actorId`
- `correlationId`
- `processId`
- `assetId`
- `agreementId`
- `negotiationId`
- `transferProcessId`
- `benchmarkRunId`
- `status`
- `details`
- `payloadHash`
- `responseHash`

### Event types to support first

- `CONTRACT_NEGOTIATION_FINALIZED`
- `TRANSFER_PROCESS_STARTED`
- `TRANSFER_PROCESS_COMPLETED`
- `MODEL_EXECUTION_REQUESTED`
- `MODEL_EXECUTION_COMPLETED`
- `MODEL_EXECUTION_FAILED`
- `BENCHMARK_STARTED`
- `BENCHMARK_COMPLETED`
- `BENCHMARK_FAILED`
- `MODEL_DETAIL_VIEWED`

## Priority Order

## Sprint 1

1. New journal APIs in `inesdata-public-portal-backend`
2. New observer UI in `inesdata-public-portal-frontend`

## Sprint 2

1. New DSP observer extensions in `inesdata-connector`
2. New journal client extension in `inesdata-connector`

## Sprint 3

1. Optional management observer extension in `inesdata-connector`
2. Optional new observability pages in `inesdata-connector-interface`

## Explicit Non-Goals for the First Iteration

- embedding observer widgets into current catalog pages
- editing current execution pages
- editing current benchmark pages
- changing existing audit extensions
- changing current participant entities or controllers
- relying on existing plain-text logs as the durable observer journal

## Final Recommendation

The safest first implementation is:

1. build the journal backend as a new bounded context
2. build the observer frontend as a separate section
3. add connector-side observer extensions as new modules
4. leave current execution and benchmark screens untouched

This is the lowest-risk path that still delivers a real model observability capability inside the existing InesData components.