package org.upm.inesdata.validator.fallback;

import org.eclipse.edc.connector.controlplane.asset.spi.domain.Asset;
import org.eclipse.edc.connector.controlplane.services.spi.asset.AssetService;
import org.eclipse.edc.connector.controlplane.transfer.spi.event.TransferProcessCompleted;
import org.eclipse.edc.connector.controlplane.transfer.spi.store.TransferProcessStore;
import org.eclipse.edc.spi.constants.CoreConstants;
import org.eclipse.edc.spi.event.Event;
import org.eclipse.edc.spi.event.EventEnvelope;
import org.eclipse.edc.spi.event.EventSubscriber;
import org.eclipse.edc.spi.monitor.Monitor;
import org.upm.inesdata.validator.model.ValidationReport;
import org.upm.inesdata.validator.model.ValidationStatus;
import org.upm.inesdata.validator.persistence.TransferProcessValidationPersistence;
import org.upm.inesdata.validator.services.RdfValidationService;
import org.upm.inesdata.validator.services.enums.RdfFormat;

import java.io.FileInputStream;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Set;
import java.util.function.Supplier;

public class AutomaticRdfValidationSubscriber implements EventSubscriber {
    private static final String EDC_NS = CoreConstants.EDC_NAMESPACE;

    private final Supplier<RdfValidationService> validationServiceProvider;
    private final Monitor monitor;
    private final TransferProcessStore transferProcessStore;
    private final AssetService assetService;
    private final Set<String> alreadyValidatedTransfers;
    private final TransferProcessValidationPersistence persistence;

    public AutomaticRdfValidationSubscriber(
            Supplier<RdfValidationService> validationServiceProvider,
            Monitor monitor,
            TransferProcessStore transferProcessStore,
            AssetService assetService,
            Set<String> alreadyValidatedTransfers,
            TransferProcessValidationPersistence persistence
    ) {
        this.validationServiceProvider = validationServiceProvider;
        this.monitor = monitor;
        this.transferProcessStore = transferProcessStore;
        this.assetService = assetService;
        this.alreadyValidatedTransfers = alreadyValidatedTransfers;
        this.persistence = persistence;
    }

    @Override
    public <E extends Event> void on(EventEnvelope<E> envelope) {
        if (!(envelope.getPayload() instanceof TransferProcessCompleted completed)) {
            return;
        }

        var transferId = completed.getTransferProcessId();
        if (alreadyValidatedTransfers.contains(transferId)) {
            monitor.debug("Transfer " + transferId + " already validated in-stream, skipping fallback.");
            return;
        }

        try {
            runFallbackValidation(transferId, completed);
        } catch (Exception e) {
            monitor.severe("Unexpected error during RDF validation fallback for transfer " + transferId, e);
        }
    }

    private void runFallbackValidation(String transferId, TransferProcessCompleted completed) throws Exception {
        var report = new ValidationReport(transferId, completed.getAssetId(), "fallback");
        var transferProcess = transferProcessStore.findById(transferId);
        if (transferProcess == null) {
            monitor.warning("TransferProcess not found: " + transferId + " - skipping fallback validation");
            report.status = ValidationStatus.SKIPPED;
            report.message = "TransferProcess not found";
            return;
        }

        if (persistence.hasDefinitiveRdfValidationInDb(transferId)) {
            monitor.info("Transfer " + transferId + " already has definitive RDF validation in DB "
                    + "(e.g. provider mirror); skipping fallback to avoid overwriting with SKIPPED.");
            return;
        }

        var validationService = validationServiceProvider.get();
        if (validationService == null) {
            monitor.info("RdfValidationService not available for transfer " + transferId + " - skipping fallback validation");
            report.status = ValidationStatus.SKIPPED;
            report.message = "RdfValidationService not available";
            persistByTransferId(transferId, report, "fallback");
            return;
        }

        var destination = transferProcess.getDataDestination();
        if (destination == null) {
            monitor.info("No dataDestination for transfer " + transferId + " - skipping fallback validation");
            report.status = ValidationStatus.SKIPPED;
            report.message = "No dataDestination";
            persistByTransferId(transferId, report, "fallback");
            return;
        }

        var rawPath = dataAddressProp(destination, "path");
        if (rawPath == null) {
            monitor.info("No local file path for transfer " + transferId + " - skipping fallback validation");
            report.status = ValidationStatus.SKIPPED;
            report.message = "No local file path";
            persistByTransferId(transferId, report, "fallback");
            return;
        }

        var filePath = Paths.get(rawPath);
        if (!Files.exists(filePath)) {
            monitor.warning("Transferred file not found at path: " + rawPath);
            report.status = ValidationStatus.ERROR;
            report.message = "Transferred file not found at path: " + rawPath;
            persistByTransferId(transferId, report, "fallback");
            return;
        }

        var fileName = filePath.getFileName().toString().toLowerCase();
        if (!isRdfFile(fileName)) {
            monitor.debug("File '" + fileName + "' is not RDF - skipping fallback validation");
            report.status = ValidationStatus.SKIPPED;
            report.message = "Transferred file is not RDF";
            persistByTransferId(transferId, report, "fallback");
            return;
        }

        var assetId = completed.getAssetId();
        var asset = assetService.findById(assetId);
        if (asset == null) {
            monitor.warning("Asset '" + assetId + "' not found - skipping fallback validation");
            report.status = ValidationStatus.SKIPPED;
            report.message = "Asset not found";
            persistByTransferId(transferId, report, "fallback");
            return;
        }

        var ontologyUrl = assetProp(asset, "ontologyDownloadUrl");
        var shaclUrl = assetProp(asset, "shaclDownloadUrl");
        report.ontologyUrl = ontologyUrl;
        report.shaclUrl = shaclUrl;
        if (shaclUrl == null || shaclUrl.isBlank()) {
            monitor.info("Asset '" + assetId + "' has no shaclDownloadUrl - skipping fallback validation");
            report.status = ValidationStatus.SKIPPED;
            report.message = "Asset has no shaclDownloadUrl";
            persistByTransferId(transferId, report, "fallback");
            return;
        }

        var format = detectRdfFormat(fileName);
        report.format = format.name();
        try (var fis = new FileInputStream(filePath.toFile())) {
            var result = validationService.validate(fis, format, ontologyUrl, shaclUrl);
            if (result.failed()) {
                var reasons = String.join("; ", result.toResult().getFailureMessages());
                report.status = ValidationStatus.FAILED;
                report.message = "SHACL validation failed";
                report.errors.addAll(result.toResult().getFailureMessages());
                monitor.warning("RDF validation FAILED (fallback) transfer=" + transferId + " asset=" + assetId + " reasons=" + reasons);
            } else {
                report.status = ValidationStatus.SUCCESS;
                report.message = "Validation passed";
                monitor.info("RDF validation PASSED (fallback) transfer=" + transferId + " asset=" + assetId);
            }
            persistByTransferId(transferId, report, "fallback");
        } catch (Exception e) {
            report.status = ValidationStatus.ERROR;
            report.message = "Validation executed with runtime errors";
            report.errors.add(e.getMessage());
            persistByTransferId(transferId, report, "fallback");
            throw e;
        }
    }

    private void persistByTransferId(String transferId, ValidationReport report, String contextLabel) {
        persistence.persistByTransferId(transferId, report, contextLabel);
    }

    private String assetProp(Asset asset, String key) {
        var value = asset.getProperties().get(EDC_NS + key);
        if (value == null) {
            value = asset.getProperties().get(key);
        }
        return value != null ? value.toString() : null;
    }

    private String dataAddressProp(org.eclipse.edc.spi.types.domain.DataAddress dataAddress, String key) {
        var value = dataAddress.getProperties().get(EDC_NS + key);
        if (value == null) {
            value = dataAddress.getProperties().get(key);
        }
        return value != null ? value.toString() : null;
    }

    private boolean isRdfFile(String fileName) {
        return fileName.endsWith(".n3") || fileName.endsWith(".ttl")
                || fileName.endsWith(".rdf") || fileName.endsWith(".owl")
                || fileName.endsWith(".nt") || fileName.endsWith(".jsonld");
    }

    private RdfFormat detectRdfFormat(String fileName) {
        if (fileName.endsWith(".n3")) return RdfFormat.N3;
        if (fileName.endsWith(".ttl")) return RdfFormat.TURTLE;
        if (fileName.endsWith(".rdf") || fileName.endsWith(".owl")) return RdfFormat.RDFXML;
        if (fileName.endsWith(".nt")) return RdfFormat.NTRIPLES;
        if (fileName.endsWith(".jsonld")) return RdfFormat.JSONLD;
        return RdfFormat.TURTLE;
    }
}
