package org.upm.inesdata.validator.persistence;

import jakarta.json.Json;
import jakarta.json.JsonObject;
import jakarta.json.JsonReader;
import jakarta.json.JsonString;
import jakarta.json.JsonValue;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.transaction.datasource.spi.DataSourceRegistry;
import org.eclipse.edc.transaction.spi.TransactionContext;
import org.upm.inesdata.validator.model.ValidationPersistenceKeys;
import org.upm.inesdata.validator.model.ValidationReport;

import java.io.StringReader;
import java.sql.SQLException;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Persists RDF validation snapshots into {@code edc_transfer_process.private_properties} under
 * keys with the {@code inesdata.rdf.validation.*} prefix using a raw JSONB merge update.
 * <p>
 * Bypasses {@code TransferProcessStore.save()} on purpose: that path participates in the EDC
 * state-machine lifecycle (lease + concurrent state advances) and was silently overwriting our
 * private-properties writes (DB row ended with {@code {}}). The JSONB concat operator
 * ({@code ||}) preserves existing keys and only updates the validation ones, so it does not
 * compete with EDC's own writes.
 */
public class TransferProcessValidationPersistence {

    private static final String UPDATE_SQL = "UPDATE edc_transfer_process " +
            "SET private_properties = COALESCE(private_properties::jsonb, '{}'::jsonb) || ?::jsonb " +
            "WHERE transferprocess_id = ?";
    private static final String UPDATE_BY_CORRELATION_SQL = "UPDATE edc_transfer_process " +
            "SET private_properties = COALESCE(private_properties::jsonb, '{}'::jsonb) || ?::jsonb " +
            "WHERE correlation_id = ? AND type = 'CONSUMER'";
    private static final String SELECT_PRIVATE_PROPERTIES_SQL =
            "SELECT COALESCE(private_properties::jsonb, '{}'::jsonb)::text AS pp FROM edc_transfer_process "
                    + "WHERE transferprocess_id = ?";

    private final DataSourceRegistry dataSourceRegistry;
    private final TransactionContext transactionContext;
    private final Monitor monitor;
    private final String dataSourceName;

    public TransferProcessValidationPersistence(DataSourceRegistry dataSourceRegistry,
                                                TransactionContext transactionContext,
                                                Monitor monitor,
                                                String dataSourceName) {
        this.dataSourceRegistry = dataSourceRegistry;
        this.transactionContext = transactionContext;
        this.monitor = monitor;
        this.dataSourceName = dataSourceName;
    }

    /**
     * Merges the given validation report into the transfer's private_properties JSON column.
     * Only keys with the {@code inesdata.rdf.validation.*} prefix are written.
     *
     * @return {@code true} if at least one database row was updated
     */
    public boolean persistByTransferId(String transferId, ValidationReport report, String contextLabel) {
        if (transferId == null || transferId.isBlank()) {
            monitor.debug("Skip RDF validation persist: blank transferId context=" + contextLabel);
            return false;
        }
        if (report == null) {
            return false;
        }

        var json = buildPropsJson(report);

        return Boolean.TRUE.equals(transactionContext.execute(() -> {
            var ds = dataSourceRegistry.resolve(dataSourceName);
            if (ds == null) {
                monitor.warning("RDF persist: datasource '" + dataSourceName + "' not found. transferId=" + transferId
                        + " context=" + contextLabel);
                return false;
            }
            try (var connection = ds.getConnection();
                 var ps = connection.prepareStatement(UPDATE_SQL)) {
                ps.setString(1, json);
                ps.setString(2, transferId);
                int rows = ps.executeUpdate();
                if (rows == 0) {
                    monitor.warning("RDF persist: no row updated. transferId=" + transferId
                            + " context=" + contextLabel);
                    return false;
                }
                monitor.info("RDF persist OK transferId=" + transferId + " status=" + report.status
                        + " context=" + contextLabel);
                return true;
            } catch (SQLException e) {
                monitor.warning("RDF persist failed transferId=" + transferId + " (" + contextLabel + "): "
                        + e.getClass().getSimpleName() + (e.getMessage() != null ? (": " + e.getMessage()) : ""));
                return false;
            }
        }));
    }

    /**
     * Reads {@code private_properties} from the DB row (not the {@link org.eclipse.edc.connector.controlplane.transfer.spi.store.TransferProcessStore}
     * cache). Used to avoid the completion-event fallback overwriting a result just written by the provider mirror (SQL JSONB merge).
     */
    public boolean hasDefinitiveRdfValidationInDb(String transferId) {
        if (transferId == null || transferId.isBlank()) {
            return false;
        }
        var sql = "SELECT private_properties::jsonb->>? AS st FROM edc_transfer_process WHERE transferprocess_id = ?";
        return Boolean.TRUE.equals(transactionContext.execute(() -> {
            var ds = dataSourceRegistry.resolve(dataSourceName);
            if (ds == null) {
                return false;
            }
            try (var connection = ds.getConnection();
                 var ps = connection.prepareStatement(sql)) {
                ps.setString(1, ValidationPersistenceKeys.STATUS);
                ps.setString(2, transferId);
                try (var rs = ps.executeQuery()) {
                    if (!rs.next()) {
                        return false;
                    }
                    var st = rs.getString("st");
                    if (st == null) {
                        return false;
                    }
                    st = st.trim();
                    return "SUCCESS".equals(st) || "FAILED".equals(st) || "ERROR".equals(st);
                }
            } catch (SQLException e) {
                monitor.debug("hasDefinitiveRdfValidationInDb failed transferId=" + transferId + ": "
                        + e.getClass().getSimpleName()
                        + (e.getMessage() != null ? (": " + e.getMessage()) : ""));
                return false;
            }
        }));
    }

    /**
     * Reads RDF validation keys from {@code edc_transfer_process.private_properties} for use when serializing
     * Management API responses. Those keys are merged via raw SQL and may be absent from the in-memory
     * {@link org.eclipse.edc.connector.controlplane.transfer.spi.types.TransferProcess#getPrivateProperties()} map.
     */
    public Map<String, String> loadRdfValidationProperties(String transferProcessId) {
        if (transferProcessId == null || transferProcessId.isBlank()) {
            return Collections.emptyMap();
        }
        var mapped = transactionContext.execute(() -> {
            var ds = dataSourceRegistry.resolve(dataSourceName);
            if (ds == null) {
                monitor.debug("RDF validation load: datasource '" + dataSourceName + "' not found. transferId="
                        + transferProcessId);
                return Collections.<String, String>emptyMap();
            }
            try (var connection = ds.getConnection();
                 var ps = connection.prepareStatement(SELECT_PRIVATE_PROPERTIES_SQL)) {
                ps.setString(1, transferProcessId);
                try (var rs = ps.executeQuery()) {
                    if (!rs.next()) {
                        return Collections.<String, String>emptyMap();
                    }
                    var raw = rs.getString("pp");
                    if (raw == null || raw.isBlank()) {
                        return Collections.<String, String>emptyMap();
                    }
                    JsonObject obj;
                    try (JsonReader reader = Json.createReader(new StringReader(raw))) {
                        obj = reader.readObject();
                    } catch (Exception e) {
                        monitor.warning("RDF validation load: invalid JSON in private_properties transferId="
                                + transferProcessId + ": " + e.getClass().getSimpleName());
                        return Collections.<String, String>emptyMap();
                    }
                    var out = new LinkedHashMap<String, String>();
                    for (var key : obj.keySet()) {
                        if (!key.startsWith(ValidationPersistenceKeys.KEY_PREFIX)) {
                            continue;
                        }
                        var v = obj.get(key);
                        if (v == null || v == JsonValue.NULL) {
                            continue;
                        }
                        if (v.getValueType() == JsonValue.ValueType.STRING) {
                            out.put(key, ((JsonString) v).getString());
                        } else {
                            out.put(key, v.toString());
                        }
                    }
                    return out;
                }
            } catch (SQLException e) {
                monitor.warning("RDF validation load failed transferId=" + transferProcessId + ": "
                        + e.getClass().getSimpleName()
                        + (e.getMessage() != null ? (": " + e.getMessage()) : ""));
                return Collections.<String, String>emptyMap();
            }
        });
        return mapped != null ? mapped : Collections.emptyMap();
    }

    public boolean persistByCorrelationId(String correlationId, ValidationReport report, String contextLabel) {
        if (correlationId == null || correlationId.isBlank() || report == null) {
            return false;
        }
        var json = buildPropsJson(report);
        return transactionContext.execute(() -> {
            var ds = dataSourceRegistry.resolve(dataSourceName);
            if (ds == null) {
                monitor.warning("RDF persist by correlation: datasource '" + dataSourceName + "' not found. correlationId=" + correlationId
                        + " context=" + contextLabel);
                return false;
            }
            try (var connection = ds.getConnection();
                 var ps = connection.prepareStatement(UPDATE_BY_CORRELATION_SQL)) {
                ps.setString(1, json);
                ps.setString(2, correlationId);
                int rows = ps.executeUpdate();
                if (rows == 0) {
                    monitor.warning("RDF persist by correlation: no row updated. correlationId=" + correlationId
                            + " context=" + contextLabel);
                    return false;
                }
                monitor.info("RDF persist OK by correlationId=" + correlationId + " status=" + report.status
                        + " context=" + contextLabel + " rows=" + rows);
                return true;
            } catch (SQLException e) {
                monitor.warning("RDF persist by correlation failed correlationId=" + correlationId + " (" + contextLabel + "): "
                        + e.getClass().getSimpleName() + (e.getMessage() != null ? (": " + e.getMessage()) : ""));
                return false;
            }
        });
    }

    private static String buildPropsJson(ValidationReport report) {
        Map<String, String> props = report.toPersistableProperties();
        var sb = new StringBuilder("{");
        boolean first = true;
        for (var entry : props.entrySet()) {
            if (!first) {
                sb.append(',');
            }
            first = false;
            sb.append('"').append(escapeJsonString(entry.getKey())).append('"')
                    .append(':')
                    .append('"').append(escapeJsonString(entry.getValue())).append('"');
        }
        sb.append('}');
        return sb.toString();
    }

    private static String escapeJsonString(String value) {
        if (value == null) {
            return "";
        }
        var sb = new StringBuilder(value.length() + 8);
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                case '\b': sb.append("\\b"); break;
                case '\f': sb.append("\\f"); break;
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
