# Model Observer DSP Events Extension

Connector extension that subscribes to DSP events and publishes normalized model observer records to the portal journal.

## Current scope

- maps `ContractNegotiationEvent` to `CONTRACT_NEGOTIATION_FINALIZED`
- maps `TransferProcessEvent` to `TRANSFER_PROCESS_STARTED` or `TRANSFER_PROCESS_COMPLETED`
- publishes each normalized event to the portal backend journal endpoint
- falls back to local monitor logging when the journal URL is not configured

## Configuration

- `model.observer.journal.enabled=true`
- `model.observer.journal.baseurl=http://localhost:1337`
- `model.observer.journal.events.path=/api/model-observer/events`
- `model.observer.source.component=inesdata-connector:model-observer-dsp-events`

## Activation status

This module is already registered in the connector Gradle settings and can be compiled as part of the project.

Current activation entry in `settings.gradle.kts`:

```kotlin
include(":extensions:model-observer-dsp-events")
```