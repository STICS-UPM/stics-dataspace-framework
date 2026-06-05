package org.eclipse.edc.validation.rdf.api.controller;

import jakarta.json.Json;
import jakarta.json.JsonObject;
import jakarta.json.JsonReader;
import jakarta.json.JsonString;
import jakarta.json.JsonValue;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.validation.rdf.model.ValidationReport;
import org.eclipse.edc.validation.rdf.model.ValidationStatus;
import org.eclipse.edc.validation.rdf.persistence.TransferProcessValidationPersistence;

import java.io.StringReader;

/**
 * Receives the same JSON the provider {@code ValidatingDataSink#notifyCallback} posts and merges
 * {@code edc.rdf.validation.*} into the <strong>consumer</strong> {@code TransferProcess#privateProperties}.
 * <p>
 * Configure the data flow (from the consumer) with:
 * <ul>
 *   <li>{@code rdfValidationCallbackUrl} = public URL to this resource (e.g. {@code https://&lt;consumer&gt;/public/validation/rdf-mirror} — must be reachable from the provider dataplane).
 *   <li>{@code consumerTransferProcessId} = the consumer {@code transferprocess_id} (from the response when starting the transfer; required to know which local row to update).
 * </ul>
 * The provider callback JSON includes the same field when the data flow sets it, plus {@code correlationId} (shared when EDC populates
 * {@code edc_transfer_process.correlation_id}) for diagnostics.
 * <p>
 * The endpoint is intentionally registered in the {@code public} web context (no auth) and always returns HTTP 200,
 * even when no row could be updated, so the provider data plane never interprets the callback as a failure: RDF
 * validation is informational and must never block the transfer.
 */
@Path("/validation/rdf-mirror")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
public class RdfValidationMirrorController {

    public static final String PATH = "/validation/rdf-mirror";

    private final TransferProcessValidationPersistence persistence;
    private final Monitor monitor;

    public RdfValidationMirrorController(TransferProcessValidationPersistence persistence, Monitor monitor) {
        this.persistence = persistence;
        this.monitor = monitor;
    }

    @POST
    @Consumes({ MediaType.APPLICATION_JSON, MediaType.WILDCARD })
    public Response postMirror(String rawBody) {
        if (rawBody == null || rawBody.isBlank()) {
            monitor.info("RDF validation mirror: empty body, returning 200 (informational).");
            return Response.ok(
                    Json.createObjectBuilder()
                            .add("stored", false)
                            .add("matchedBy", "none")
                            .add("message", "empty body")
                            .build()
            ).build();
        }

        JsonObject body;
        try (JsonReader reader = Json.createReader(new StringReader(rawBody))) {
            body = reader.readObject();
        } catch (Exception e) {
            monitor.warning("RDF validation mirror: invalid JSON, returning 200 anyway: "
                    + e.getClass().getSimpleName() + (e.getMessage() != null ? (": " + e.getMessage()) : ""));
            return Response.ok(
                    Json.createObjectBuilder()
                            .add("stored", false)
                            .add("matchedBy", "none")
                            .add("message", "invalid JSON")
                            .build()
            ).build();
        }
        var consumerId = getStringOrEmpty(body, "consumerTransferProcessId");
        var correlationId = getStringOrEmpty(body, "correlationId");
        var providerTransferId = getStringOrEmpty(body, "providerTransferProcessId");
        if (correlationId.isBlank()) {
            correlationId = getStringOrEmpty(body, "transferId");
        }
        if (correlationId.isBlank()) {
            correlationId = providerTransferId;
        }

        var report = parseReport(body, consumerId);
        var stored = false;
        var matchedBy = "none";

        try {
            if (!consumerId.isBlank()) {
                stored = persistence.persistByTransferId(consumerId, report, "rdf-callback-mirror");
                if (stored) {
                    matchedBy = "consumerTransferProcessId";
                    monitor.info("RDF validation result mirrored using consumerTransferProcessId: " + consumerId);
                }
            }
            if (!stored && !correlationId.isBlank()
                    && persistence.persistByCorrelationId(correlationId, report, "rdf-callback-mirror-correlation")) {
                stored = true;
                matchedBy = "correlationId";
                monitor.info("RDF validation result mirrored using correlationId/providerTransferId: " + correlationId);
            }
            if (!stored) {
                monitor.info("RDF validation mirror received without a matching consumer row. "
                        + "consumerTransferProcessId='" + consumerId + "' correlationId='" + correlationId
                        + "' providerTransferProcessId='" + providerTransferId + "'. Returning 200 (informational).");
            }
        } catch (Exception e) {
            // Never propagate errors to the provider: RDF validation is informational and must not block the transfer.
            monitor.warning("RDF validation mirror persist threw exception, returning 200 anyway: "
                    + e.getClass().getSimpleName()
                    + (e.getMessage() != null ? (": " + e.getMessage()) : ""));
        }

        return Response.ok(
                Json.createObjectBuilder()
                        .add("stored", stored)
                        .add("matchedBy", matchedBy)
                        .add("targetTransferProcessId", consumerId)
                        .add("correlationId", correlationId)
                        .add("providerTransferProcessId", providerTransferId)
                        .build()
        ).build();
    }

    private static ValidationReport parseReport(JsonObject body, String targetConsumerId) {
        var transferId = getStringOrEmpty(body, "transferId");
        if (transferId.isEmpty()) {
            transferId = getStringOrEmpty(body, "providerTransferProcessId");
        }
        var report = new ValidationReport(
                transferId,
                getStringOrEmpty(body, "assetId"),
                getStringOrEmpty(body, "destinationType", "unknown")
        );
        report.resolvedAssetId = getStringOrEmpty(body, "assetId");
        report.correlationId = getStringOrEmpty(body, "correlationId");
        report.consumerTransferProcessId = targetConsumerId;
        report.format = getStringOrEmpty(body, "format", "unknown");
        report.message = getStringOrEmpty(body, "message");
        report.ontologyUrl = getStringOrEmpty(body, "ontologyUrl");
        report.shaclUrl = getStringOrEmpty(body, "shaclUrl");
        if (body.containsKey("status")) {
            try {
                report.status = ValidationStatus.valueOf(getStringOrEmpty(body, "status", "SKIPPED"));
            } catch (IllegalArgumentException e) {
                report.status = ValidationStatus.SKIPPED;
            }
        }
        if (body.containsKey("errors") && body.get("errors") != null && !body.isNull("errors")) {
            var arr = body.getJsonArray("errors");
            for (var v : arr) {
                if (v != null && v.getValueType() == JsonValue.ValueType.STRING) {
                    report.errors.add(((JsonString) v).getString());
                } else {
                    report.errors.add(String.valueOf(v));
                }
            }
        }
        return report;
    }

    private static String getStringOrEmpty(JsonObject o, String key) {
        if (!o.containsKey(key) || o.isNull(key)) {
            return "";
        }
        var v = o.get(key);
        if (v.getValueType() == JsonValue.ValueType.STRING) {
            return o.getString(key);
        }
        return String.valueOf(v);
    }

    private static String getStringOrEmpty(JsonObject o, String key, String def) {
        var s = getStringOrEmpty(o, key);
        return s.isEmpty() ? def : s;
    }
}
