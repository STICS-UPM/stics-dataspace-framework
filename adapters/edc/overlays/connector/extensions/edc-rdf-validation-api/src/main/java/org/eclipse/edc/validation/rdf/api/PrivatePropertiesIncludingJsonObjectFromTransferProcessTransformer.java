package org.eclipse.edc.validation.rdf.api.transform;

import jakarta.json.JsonBuilderFactory;
import jakarta.json.JsonObject;
import org.eclipse.edc.connector.controlplane.api.management.transferprocess.transform.JsonObjectFromTransferProcessTransformer;
import org.eclipse.edc.connector.controlplane.transfer.spi.types.TransferProcess;
import org.eclipse.edc.jsonld.spi.transformer.AbstractJsonLdTransformer;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.transform.spi.TransformerContext;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;
import org.eclipse.edc.validation.rdf.persistence.TransferProcessValidationPersistence;

import java.util.Map;

import static org.eclipse.edc.spi.constants.CoreConstants.EDC_NAMESPACE;

/**
 * EDC's stock {@link JsonObjectFromTransferProcessTransformer} omits
 * {@link TransferProcess#getPrivateProperties()} from management API JSON.
 * RDF validation snapshots are merged into {@code edc_transfer_process.private_properties} via SQL;
 * that bypasses the in-memory map, so we merge DB-backed {@code edc.rdf.validation.*} keys here.
 * <p>
 * Delegates to the stock transformer, then copies all entries into a new builder and
 * adds {@link TransferProcess#TRANSFER_PROCESS_PRIVATE_PROPERTIES}.
 */
public class PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer extends AbstractJsonLdTransformer<TransferProcess, JsonObject> {

    private final JsonObjectFromTransferProcessTransformer delegate;
    private final JsonBuilderFactory builderFactory;
    private final Monitor monitor;
    private final TransferProcessValidationPersistence validationPersistence;

    public PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer(JsonBuilderFactory builderFactory,
                                                                              Monitor monitor,
                                                                              TransferProcessValidationPersistence validationPersistence) {
        super(TransferProcess.class, JsonObject.class);
        this.builderFactory = builderFactory;
        this.delegate = new JsonObjectFromTransferProcessTransformer(builderFactory);
        this.monitor = monitor;
        this.validationPersistence = validationPersistence;
    }

    @Override
    public @Nullable JsonObject transform(@NotNull TransferProcess input, @NotNull TransformerContext context) {
        Map<?, ?> privateProps = input.getPrivateProperties();
        if (monitor != null) {
            monitor.debug("PrivatePropertiesIncluding transfer transform: transferId="
                    + input.getId()
                    + " privatePropertiesSize=" + (privateProps == null ? -1 : privateProps.size())
                    + " keys=" + (privateProps == null ? "null" : privateProps.keySet()));
        }
        var base = delegate.transform(input, context);
        if (base == null) {
            return null;
        }
        var builder = builderFactory.createObjectBuilder();
        base.forEach(builder::add);

        var propsBuilder = builderFactory.createObjectBuilder();
        if (privateProps != null && !privateProps.isEmpty()) {
            privateProps.forEach((key, value) -> {
                if (key != null && value != null) {
                    propsBuilder.add(toIri(key.toString()), value.toString());
                }
            });
        }
        if (input.getId() != null) {
            validationPersistence.loadRdfValidationProperties(input.getId())
                    .forEach((k, v) -> propsBuilder.add(toIri(k), v));
        }
        var built = propsBuilder.build();
        if (!built.isEmpty()) {
            builder.add(TransferProcess.TRANSFER_PROCESS_PRIVATE_PROPERTIES, built);
        }

        return builder.build();
    }

    /**
     * Promote plain keys (e.g. {@code edc.rdf.validation.status}) to absolute IRIs so they survive
     * {@link org.eclipse.edc.web.jersey.providers.jsonld.JerseyJsonLdInterceptor#aroundWriteTo} compaction
     * (Titanium expand-then-compact drops nested keys that have no IRI mapping). Compaction with
     * {@code @vocab=EDC_NAMESPACE} (registered in {@code SharedApiConfigurationExtension}) contracts the
     * IRI back to the original short form on the wire.
     */
    private static String toIri(String key) {
        if (key == null) {
            return null;
        }
        return (key.startsWith("http://") || key.startsWith("https://")) ? key : EDC_NAMESPACE + key;
    }
}
