package org.upm.inesdata.validator.model;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class ValidationReport {
    public final String transferId;
    public final String assetId;
    /** Filled when {@code DataFlowStartMessage} has no assetId but the transfer process does (e.g. provider PUSH). */
    public String resolvedAssetId;
    public final String destinationType;
    public final Instant timestamp = Instant.now();
    public ValidationStatus status = ValidationStatus.SKIPPED;
    public String format = "unknown";
    public String message = "";
    public String ontologyUrl = "";
    public String shaclUrl = "";
    public final List<String> errors = new ArrayList<>();
    /**
     * Control-plane {@code TransferProcess#getCorrelationId()} of the data-plane transfer (e.g. provider), for linking to consumer.
     */
    public String correlationId = "";
    /**
     * Target consumer {@code transferprocess_id} set on the data flow (property {@code consumerTransferProcessId}) so a callback can update that row.
     */
    public String consumerTransferProcessId = "";

    public ValidationReport(String transferId, String assetId, String destinationType) {
        this.transferId = transferId;
        this.assetId = assetId;
        this.resolvedAssetId = assetId;
        this.destinationType = destinationType;
    }

    public String effectiveAssetId() {
        if (resolvedAssetId != null && !resolvedAssetId.isBlank()) {
            return resolvedAssetId;
        }
        return assetId;
    }

    public String toJson() {
        var escapedErrors = errors.stream()
                .map(ValidationReport::escapeJson)
                .map(s -> "\"" + s + "\"")
                .reduce((a, b) -> a + "," + b)
                .orElse("");

        return "{"
                + "\"transferId\":\"" + escapeJson(transferId) + "\","
                + "\"providerTransferProcessId\":\"" + escapeJson(transferId) + "\","
                + "\"correlationId\":\"" + escapeJson(correlationId) + "\","
                + "\"consumerTransferProcessId\":\"" + escapeJson(consumerTransferProcessId) + "\","
                + "\"assetId\":\"" + escapeJson(effectiveAssetId() == null ? "" : effectiveAssetId()) + "\","
                + "\"destinationType\":\"" + escapeJson(destinationType == null ? "" : destinationType) + "\","
                + "\"status\":\"" + escapeJson(status.name()) + "\","
                + "\"format\":\"" + escapeJson(format) + "\","
                + "\"message\":\"" + escapeJson(message) + "\","
                + "\"ontologyUrl\":\"" + escapeJson(ontologyUrl) + "\","
                + "\"shaclUrl\":\"" + escapeJson(shaclUrl) + "\","
                + "\"timestamp\":\"" + timestamp + "\","
                + "\"errors\":[" + escapedErrors + "]"
                + "}";
    }

    public Map<String, String> toPersistableProperties() {
        var properties = new LinkedHashMap<String, String>();
        properties.put(ValidationPersistenceKeys.STATUS, status != null ? status.name() : ValidationStatus.SKIPPED.name());
        properties.put(ValidationPersistenceKeys.MESSAGE, safeValue(message));
        properties.put(ValidationPersistenceKeys.TRANSFER_ID, safeValue(transferId));
        properties.put(ValidationPersistenceKeys.ASSET_ID, safeValue(effectiveAssetId()));
        properties.put(ValidationPersistenceKeys.FORMAT, safeValue(format));
        properties.put(ValidationPersistenceKeys.ONTOLOGY_URL, safeValue(ontologyUrl));
        properties.put(ValidationPersistenceKeys.SHACL_URL, safeValue(shaclUrl));
        properties.put(ValidationPersistenceKeys.ERRORS, String.join("; ", errors));
        properties.put(ValidationPersistenceKeys.TIMESTAMP, timestamp.toString());
        return properties;
    }

    private static String safeValue(String value) {
        return value == null ? "" : value;
    }

    private static String escapeJson(String value) {
        if (value == null) {
            return "";
        }
        var sb = new StringBuilder(value.length() + 8);
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '\\':
                    sb.append("\\\\");
                    break;
                case '"':
                    sb.append("\\\"");
                    break;
                case '\n':
                    sb.append("\\n");
                    break;
                case '\r':
                    sb.append("\\r");
                    break;
                case '\t':
                    sb.append("\\t");
                    break;
                case '\b':
                    sb.append("\\b");
                    break;
                case '\f':
                    sb.append("\\f");
                    break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        return sb.toString();
    }
}
