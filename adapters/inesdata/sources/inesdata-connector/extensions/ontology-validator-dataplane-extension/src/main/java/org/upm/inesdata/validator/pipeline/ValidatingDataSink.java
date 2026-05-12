package org.upm.inesdata.validator.pipeline;

import org.eclipse.edc.connector.controlplane.asset.spi.domain.Asset;
import org.eclipse.edc.connector.controlplane.services.spi.asset.AssetService;
import org.eclipse.edc.connector.controlplane.transfer.spi.store.TransferProcessStore;
import org.eclipse.edc.connector.dataplane.spi.pipeline.DataSink;
import org.eclipse.edc.connector.dataplane.spi.pipeline.DataSource;
import org.eclipse.edc.connector.dataplane.spi.pipeline.StreamResult;
import org.eclipse.edc.spi.constants.CoreConstants;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.types.domain.transfer.DataFlowStartMessage;
import org.upm.inesdata.validator.model.ValidationMetadata;
import org.upm.inesdata.validator.model.ValidationReport;
import org.upm.inesdata.validator.model.ValidationStatus;
import org.upm.inesdata.validator.persistence.TransferProcessValidationPersistence;
import org.upm.inesdata.validator.services.RdfValidationService;
import org.upm.inesdata.validator.services.enums.RdfFormat;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.concurrent.CompletableFuture;
import java.util.function.Supplier;

class ValidatingDataSink implements DataSink {
    private static final String EDC_NS = CoreConstants.EDC_NAMESPACE;

    private final DataSink delegate;
    private final DataFlowStartMessage request;
    private final Supplier<RdfValidationService> validationServiceProvider;
    private final Monitor monitor;
    private final AssetService assetService;
    private final TransferProcessStore transferProcessStore;
    private final TransferProcessValidationPersistence persistence;
    private final String runtimeParticipantId;
    private final Set<String> alreadyValidatedTransfers;

    ValidatingDataSink(
            DataSink delegate,
            DataFlowStartMessage request,
            Supplier<RdfValidationService> validationServiceProvider,
            Monitor monitor,
            AssetService assetService,
            TransferProcessStore transferProcessStore,
            String runtimeParticipantId,
            Set<String> alreadyValidatedTransfers,
            TransferProcessValidationPersistence persistence
    ) {
        this.delegate = delegate;
        this.request = request;
        this.validationServiceProvider = validationServiceProvider;
        this.monitor = monitor;
        this.assetService = assetService;
        this.transferProcessStore = transferProcessStore;
        this.persistence = persistence;
        this.runtimeParticipantId = runtimeParticipantId;
        this.alreadyValidatedTransfers = alreadyValidatedTransfers;
    }

    @Override
    public CompletableFuture<StreamResult<Object>> transfer(DataSource source) {
        var spooledResult = spoolSource(source);
        if (spooledResult.failed()) {
            return CompletableFuture.completedFuture(StreamResult.error(spooledResult.getFailureDetail()));
        }

        var spooledSource = spooledResult.getContent();
        var report = validate(spooledSource);
        alreadyValidatedTransfers.add(request.getProcessId());
        logReport(report);
        notifyCallback(report);

        CompletableFuture<StreamResult<Object>> future;
        try {
            future = delegate.transfer(spooledSource);
        } catch (Exception e) {
            spooledSource.cleanup();
            persistAfterTransferSafe(report, "setup-failed");
            return CompletableFuture.completedFuture(StreamResult.error("Sink transfer setup failed: " + e.getMessage()));
        }

        // Persist only after the sink finishes: updating TransferProcess during the active data flow can race
        // the control plane state machine and leave transfers stuck (e.g. STARTED).
        return future.whenComplete((result, throwable) -> {
            spooledSource.cleanup();
            persistAfterTransferSafe(report, throwable != null ? "transfer-failed" : "after-transfer");
        });
    }

    private void persistAfterTransferSafe(ValidationReport report, String phase) {
        try {
            persistence.persistByTransferId(report.transferId, report, "in-stream-" + phase);
        } catch (Exception e) {
            monitor.warning("RDF post-transfer privateProperties persist failed (" + phase + "): " + e.getClass().getSimpleName()
                    + (e.getMessage() != null ? (": " + e.getMessage()) : ""));
        }
    }

    private StreamResult<SpooledDataSource> spoolSource(DataSource source) {
        var partsResult = source.openPartStream();
        if (partsResult.failed()) {
            return StreamResult.failure(partsResult.getFailure());
        }
        if (partsResult.getContent() == null) {
            return StreamResult.error("Data source returned no parts");
        }

        var spooledParts = new ArrayList<SpooledPart>();
        try (var parts = partsResult.getContent()) {
            parts.forEach(part -> {
                try {
                    var tempPath = Files.createTempFile("rdf-transfer-" + request.getProcessId() + "-", ".part");
                    try (var input = part.openStream()) {
                        Files.copy(input, tempPath, StandardCopyOption.REPLACE_EXISTING);
                    }
                    spooledParts.add(new SpooledPart(part.name(), part.mediaType(), tempPath));
                } catch (IOException e) {
                    throw new RuntimeException(e);
                }
            });
            return StreamResult.success(new SpooledDataSource(spooledParts));
        } catch (Exception e) {
            spooledParts.forEach(SpooledPart::deleteQuietly);
            return StreamResult.error("Unable to spool transfer stream for validation: " + e.getMessage());
        }
    }

    private ValidationReport validate(SpooledDataSource spooledSource) {
        var report = new ValidationReport(
                request.getProcessId(),
                request.getAssetId(),
                request.getDestinationDataAddress() != null ? request.getDestinationDataAddress().getType() : "unknown"
        );
        enrichRdfCallbackFields(report);

        var flowParticipant = request.getParticipantId();
        if (flowParticipant != null && !flowParticipant.equals(runtimeParticipantId)) {
            report.status = ValidationStatus.SKIPPED;
            report.message = "In-stream validation skipped on non-consumer runtime. flowParticipant="
                    + flowParticipant + ", runtimeParticipant=" + runtimeParticipantId;
            return report;
        }

        var validationService = validationServiceProvider.get();
        if (validationService == null) {
            report.status = ValidationStatus.SKIPPED;
            report.message = "RdfValidationService unavailable";
            return report;
        }

        var metadata = resolveMetadataForTransfer(report);
        if (metadata.shaclUrl == null || metadata.shaclUrl.isBlank()) {
            report.status = ValidationStatus.SKIPPED;
            report.message = "No SHACL URL configured";
            return report;
        }

        var rdfParts = spooledSource.parts.stream().filter(this::isRdfCandidate).toList();
        if (rdfParts.isEmpty()) {
            report.status = ValidationStatus.SKIPPED;
            report.message = "No RDF payload detected in transfer stream";
            return report;
        }

        var hadFailures = false;
        var hadErrors = false;
        for (var part : rdfParts) {
            var format = detectRdfFormat(part.name, part.mediaType);
            report.format = format.name();
            try (var input = Files.newInputStream(part.path)) {
                var validationResult = validationService.validate(input, format, metadata.ontologyUrl, metadata.shaclUrl);
                if (validationResult.failed()) {
                    hadFailures = true;
                    report.errors.addAll(validationResult.toResult().getFailureMessages());
                }
            } catch (Exception e) {
                hadErrors = true;
                report.errors.add(e.getMessage());
            }
        }

        if (hadErrors) {
            report.status = ValidationStatus.ERROR;
            report.message = "Validation executed with runtime errors";
        } else if (hadFailures) {
            report.status = ValidationStatus.FAILED;
            report.message = "SHACL validation failed";
        } else {
            report.status = ValidationStatus.SUCCESS;
            report.message = "Validation passed";
        }
        return report;
    }

    /**
     * Fills {@link ValidationReport#resolvedAssetId}, {@link ValidationReport#ontologyUrl}, {@link ValidationReport#shaclUrl} and logs
     * how URLs were obtained. On the provider dataplane, {@link DataFlowStartMessage#getAssetId()} is often null even though
     * the contract references an asset: we resolve the id from {@link org.eclipse.edc.connector.controlplane.transfer.spi.types.TransferProcess}.
     */
    private ValidationMetadata resolveMetadataForTransfer(ValidationReport report) {
        var ontologyUrl = nullToEmpty(requestProperty("ontologyDownloadUrl"));
        var shaclUrl = nullToEmpty(requestProperty("shaclDownloadUrl"));

        var requestAssetId = request.getAssetId();
        var transferProcessAssetId = (String) null;
        var resolvedAssetId = requestAssetId;
        if (isBlank(resolvedAssetId)) {
            var tp = findTransferProcess(request.getProcessId());
            if (tp != null) {
                transferProcessAssetId = tp.getAssetId();
                if (!isBlank(transferProcessAssetId)) {
                    resolvedAssetId = transferProcessAssetId;
                }
            }
        }

        Asset asset = null;
        if (!isBlank(resolvedAssetId)) {
            asset = assetService.findById(resolvedAssetId);
            if (asset != null) {
                if (isBlank(ontologyUrl)) {
                    ontologyUrl = nullToEmpty(assetProperty(asset, "ontologyDownloadUrl"));
                }
                if (isBlank(shaclUrl)) {
                    shaclUrl = nullToEmpty(assetProperty(asset, "shaclDownloadUrl"));
                }
            }
        }

        report.resolvedAssetId = resolvedAssetId;
        report.ontologyUrl = ontologyUrl;
        report.shaclUrl = shaclUrl;

        var props = request.getProperties();
        var keys = formatDataFlowPropertyKeys(props);
        monitor.info("RDF_VALIDATION_METADATA transferId=" + request.getProcessId()
                + " dataFlowRequestAssetId=" + requestAssetId
                + " transferProcessAssetId=" + transferProcessAssetId
                + " effectiveAssetId=" + defaultDash(resolvedAssetId)
                + " assetFoundInCatalog=" + (asset != null)
                + " ontologyUrl=\"" + ontologyUrl + "\""
                + " shaclUrl=\"" + shaclUrl + "\""
                + " dataFlowPropertyKeys=" + keys);

        if (report.destinationType != null && "AmazonS3".equalsIgnoreCase(report.destinationType)) {
            monitor.info("RDF_VALIDATION_ARCHITECTURE transferId=" + request.getProcessId()
                    + " note=\"PUSH-to-S3/MinIO: the dataplane that opens the S3 sink usually runs the in-stream check; the consumer control-plane transfer has another id. Fallback without local file path on the consumer is expected.\"");
        }

        return new ValidationMetadata(isBlank(ontologyUrl) ? null : ontologyUrl, isBlank(shaclUrl) ? null : shaclUrl);
    }

    /**
     * Fills {@link org.upm.inesdata.validator.model.ValidationReport#correlationId} and
     * {@link org.upm.inesdata.validator.model.ValidationReport#consumerTransferProcessId} for HTTP callback payloads.
     * <p>EDC 0.12+ control-plane {@code TransferProcess} may expose a shared {@code correlationId} in
     * {@code edc_transfer_process.correlation_id} between consumer and provider processes of the same transfer; use
     * {@code consumerTransferProcessId} on the data flow when a direct id is available from the consumer UI.
     */
    private void enrichRdfCallbackFields(ValidationReport report) {
        report.consumerTransferProcessId = nullToEmpty(requestProperty("consumerTransferProcessId"));
        var tp = findTransferProcess(request.getProcessId());
        report.correlationId = nullToEmpty(extractCorrelationId(tp));
    }

    private static String extractCorrelationId(org.eclipse.edc.connector.controlplane.transfer.spi.types.TransferProcess tp) {
        if (tp == null) {
            return null;
        }
        try {
            var m = tp.getClass().getMethod("getCorrelationId");
            var v = m.invoke(tp);
            return v != null ? v.toString() : null;
        } catch (ReflectiveOperationException e) {
            return null;
        }
    }

    private org.eclipse.edc.connector.controlplane.transfer.spi.types.TransferProcess findTransferProcess(String transferId) {
        if (isBlank(transferId)) {
            return null;
        }
        try {
            return transferProcessStore.findById(transferId);
        } catch (Exception e) {
            monitor.debug("TransferProcessStore.findById failed for " + transferId + ": " + e.getClass().getSimpleName()
                    + (e.getMessage() != null ? (": " + e.getMessage()) : ""));
            return null;
        }
    }

    private static String formatDataFlowPropertyKeys(Map<String, ?> properties) {
        if (properties == null || properties.isEmpty()) {
            return "[]";
        }
        return properties.keySet().stream().limit(30).collect(Collectors.toList()).toString();
    }

    private static String nullToEmpty(String s) {
        return s == null ? "" : s;
    }

    private static String defaultDash(String s) {
        return s == null || s.isBlank() ? "null" : s;
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    private String requestProperty(String key) {
        var props = request.getProperties();
        if (props != null) {
            var value = props.get(key);
            if (value == null) {
                value = props.get(EDC_NS + key);
            }
            if (value != null) {
                return value.toString();
            }
        }
        var dest = request.getDestinationDataAddress();
        if (dest != null) {
            var dp = dest.getProperties();
            if (dp != null) {
                var value = dp.get(key);
                if (value == null) {
                    value = dp.get(EDC_NS + key);
                }
                if (value != null) {
                    return value.toString();
                }
            }
        }
        return null;
    }

    private String assetProperty(Asset asset, String key) {
        var value = asset.getProperties().get(EDC_NS + key);
        if (value == null) {
            value = asset.getProperties().get(key);
        }
        return value != null ? value.toString() : null;
    }

    private boolean isRdfCandidate(SpooledPart part) {
        var lowerName = part.name.toLowerCase();
        if (lowerName.endsWith(".n3") || lowerName.endsWith(".ttl") || lowerName.endsWith(".rdf")
                || lowerName.endsWith(".owl") || lowerName.endsWith(".nt") || lowerName.endsWith(".jsonld")) {
            return true;
        }

        if (part.mediaType == null) {
            return false;
        }

        var lowerMediaType = part.mediaType.toLowerCase();
        return lowerMediaType.contains("rdf")
                || lowerMediaType.contains("turtle")
                || lowerMediaType.contains("n-triples")
                || lowerMediaType.contains("ld+json")
                || lowerMediaType.contains("n3");
    }

    private RdfFormat detectRdfFormat(String fileName, String mediaType) {
        var lowerName = fileName != null ? fileName.toLowerCase() : "";
        var lowerMediaType = mediaType != null ? mediaType.toLowerCase() : "";

        if (lowerName.endsWith(".n3") || lowerMediaType.contains("text/n3")) return RdfFormat.N3;
        if (lowerName.endsWith(".ttl") || lowerMediaType.contains("turtle")) return RdfFormat.TURTLE;
        if (lowerName.endsWith(".rdf") || lowerName.endsWith(".owl") || lowerMediaType.contains("rdf+xml")) return RdfFormat.RDFXML;
        if (lowerName.endsWith(".nt") || lowerMediaType.contains("n-triples")) return RdfFormat.NTRIPLES;
        if (lowerName.endsWith(".jsonld") || lowerMediaType.contains("ld+json")) return RdfFormat.JSONLD;
        return RdfFormat.TURTLE;
    }

    private void logReport(ValidationReport report) {
        var base = "RDF_VALIDATION transferId=" + report.transferId
                + " assetId=" + defaultDash(report.effectiveAssetId())
                + " destinationType=" + report.destinationType
                + " status=" + report.status
                + " format=" + report.format
                + " ontologyUrl=\"" + report.ontologyUrl + "\""
                + " shaclUrl=\"" + report.shaclUrl + "\""
                + " message=\"" + report.message + "\"";

        if (report.status == ValidationStatus.FAILED || report.status == ValidationStatus.ERROR) {
            monitor.warning(base + " errors=" + report.errors);
        } else {
            monitor.info(base);
        }
    }

    private void notifyCallback(ValidationReport report) {
        var callbackUrl = requestProperty("rdfValidationCallbackUrl");
        if (callbackUrl == null || callbackUrl.isBlank()) {
            return;
        }

        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(callbackUrl).openConnection();
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setDoOutput(true);
            connection.setConnectTimeout(5000);
            connection.setReadTimeout(5000);

            var body = report.toJson();
            try (var output = connection.getOutputStream()) {
                output.write(body.getBytes(StandardCharsets.UTF_8));
            }

            var statusCode = connection.getResponseCode();
            if (statusCode >= 400) {
                var errBody = readErrorBody(connection);
                monitor.warning("RDF validation callback returned HTTP " + statusCode + " for transfer " + report.transferId
                        + " url=" + callbackUrl + (errBody.isBlank() ? "" : (" body=" + errBody)));
            }
        } catch (Exception e) {
            monitor.warning("Unable to notify RDF validation callback for transfer " + report.transferId + ": " + e.getMessage());
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static String readErrorBody(HttpURLConnection connection) {
        try (var stream = connection.getErrorStream()) {
            if (stream == null) {
                return "";
            }
            return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "";
        }
    }
}
