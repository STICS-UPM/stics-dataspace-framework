package org.upm.inesdata.modelobserver.dsp;

import org.eclipse.edc.connector.controlplane.contract.spi.event.contractnegotiation.ContractNegotiationEvent;
import org.eclipse.edc.connector.controlplane.transfer.spi.event.TransferProcessEvent;
import org.eclipse.edc.spi.event.Event;
import org.eclipse.edc.spi.event.EventEnvelope;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Locale;
import java.util.UUID;

public class ModelObserverDspEventMapper {
    private final String participantId;
    private final String sourceComponent;

    public ModelObserverDspEventMapper(String participantId, String sourceComponent) {
        this.participantId = participantId;
        this.sourceComponent = sourceComponent;
    }

    public <E extends Event> Map<String, Object> map(EventEnvelope<E> envelope) {
        if (envelope.getPayload() instanceof ContractNegotiationEvent payload) {
            return mapContractNegotiation(payload);
        }

        if (envelope.getPayload() instanceof TransferProcessEvent payload) {
            return mapTransferProcess(payload);
        }

        return null;
    }

    private Map<String, Object> mapContractNegotiation(ContractNegotiationEvent payload) {
        var eventState = payload.getClass().getSimpleName();
        Map<String, Object> event = baseEvent("CONTRACT_NEGOTIATION_FINALIZED");
        event.put("negotiationId", payload.getContractNegotiationId());
        event.put("participantId", participantId);
        event.put("providerParticipantId", payload.getCounterPartyId());
        event.put("consumerParticipantId", participantId);
        event.put("status", toUpperSnakeCase(eventState));
        event.put("details", Map.of(
                "sourceEventClass", payload.getClass().getName(),
                "counterPartyId", payload.getCounterPartyId(),
                "state", eventState
        ));
        event.put("rawEvent", Map.of(
                "contractNegotiationId", payload.getContractNegotiationId(),
                "counterPartyId", payload.getCounterPartyId(),
                "state", eventState
        ));
        return event;
    }

    private Map<String, Object> mapTransferProcess(TransferProcessEvent payload) {
        var eventType = "TRANSFER_PROCESS_STARTED";
        if (payload.getType() != null && payload.getType().toLowerCase().contains("complete")) {
            eventType = "TRANSFER_PROCESS_COMPLETED";
        }

        Map<String, Object> event = baseEvent(eventType);
        event.put("agreementId", payload.getContractId());
        event.put("transferProcessId", payload.getTransferProcessId());
        event.put("assetId", payload.getAssetId());
        event.put("participantId", participantId);
        event.put("status", payload.getType());
        event.put("details", Map.of(
                "sourceEventClass", payload.getClass().getName(),
                "transferType", payload.getType(),
                "assetId", payload.getAssetId()
        ));
        event.put("rawEvent", Map.of(
                "transferProcessId", payload.getTransferProcessId(),
                "contractId", payload.getContractId(),
                "assetId", payload.getAssetId(),
                "type", payload.getType()
        ));
        return event;
    }

    private Map<String, Object> baseEvent(String eventType) {
        Map<String, Object> event = new LinkedHashMap<>();
        event.put("eventId", UUID.randomUUID().toString());
        event.put("eventType", eventType);
        event.put("occurredAt", Instant.now().toString());
        event.put("sourceComponent", sourceComponent);
        event.put("participantId", participantId);
        return event;
    }

    private String toUpperSnakeCase(String value) {
        if (value == null || value.isBlank()) {
            return "UNKNOWN";
        }

        return value
                .replaceAll("([a-z0-9])([A-Z])", "$1_$2")
                .toUpperCase(Locale.ROOT);
    }
}