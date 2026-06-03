package org.eclipse.edc.validation.rdf.api;

import jakarta.json.Json;
import jakarta.json.JsonBuilderFactory;
import org.eclipse.edc.connector.controlplane.api.management.transferprocess.transform.JsonObjectFromTransferStateTransformer;
import org.eclipse.edc.connector.controlplane.api.management.transferprocess.transform.JsonObjectToSuspendTransferTransformer;
import org.eclipse.edc.connector.controlplane.api.management.transferprocess.transform.JsonObjectToTerminateTransferTransformer;
import org.eclipse.edc.connector.controlplane.api.management.transferprocess.transform.JsonObjectToTransferRequestTransformer;
import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;
import org.eclipse.edc.transaction.datasource.spi.DataSourceRegistry;
import org.eclipse.edc.transaction.spi.TransactionContext;
import org.eclipse.edc.transform.spi.TypeTransformer;
import org.eclipse.edc.transform.spi.TypeTransformerRegistry;
import org.eclipse.edc.web.spi.WebService;
import org.eclipse.edc.validation.rdf.api.controller.RdfValidationMirrorController;
import org.eclipse.edc.validation.rdf.api.transform.PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer;
import org.eclipse.edc.validation.rdf.persistence.TransferProcessValidationPersistence;

import java.lang.reflect.Field;
import java.util.Collections;
import java.util.List;

@Extension(value = EdcRdfValidationApiExtension.NAME)
public class EdcRdfValidationApiExtension implements ServiceExtension {

    public static final String NAME = "EDC RDF Validation API";

    @Inject
    private WebService webService;
    @Inject
    private TypeTransformerRegistry transformerRegistry;
    @Inject
    private DataSourceRegistry dataSourceRegistry;
    @Inject
    private TransactionContext transactionContext;
    @Inject
    private Monitor monitor;

    private JsonBuilderFactory managementApiJsonBuilderFactory;
    private TransferProcessValidationPersistence validationPersistence;

    @Override
    public String name() {
        return NAME;
    }

    @Override
    public void initialize(ServiceExtensionContext context) {
        this.managementApiJsonBuilderFactory = Json.createBuilderFactory(Collections.emptyMap());
        TypeTransformerRegistry managementApiTransformerRegistry = this.transformerRegistry.forContext("management-api");
        managementApiTransformerRegistry.register(new JsonObjectFromTransferStateTransformer(this.managementApiJsonBuilderFactory));
        managementApiTransformerRegistry.register(new JsonObjectToTerminateTransferTransformer());
        managementApiTransformerRegistry.register(new JsonObjectToSuspendTransferTransformer());
        managementApiTransformerRegistry.register(new JsonObjectToTransferRequestTransformer());

        this.validationPersistence = new TransferProcessValidationPersistence(
                this.dataSourceRegistry, this.transactionContext, context.getMonitor(), DataSourceRegistry.DEFAULT_DATASOURCE);

        this.webService.registerResource("public",
                new RdfValidationMirrorController(this.validationPersistence, context.getMonitor()));
    }

    @Override
    public void start() {
        prependPrivatePropertiesTransformer(
                this.transformerRegistry.forContext("management-api"),
                new PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer(
                        this.managementApiJsonBuilderFactory, this.monitor, this.validationPersistence));
    }

    @SuppressWarnings({ "unchecked", "rawtypes" })
    private void prependPrivatePropertiesTransformer(TypeTransformerRegistry managementApiRegistry,
                                                     PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer transformer) {
        Field transformersField = null;
        for (Class<?> c = managementApiRegistry.getClass(); c != null && transformersField == null; c = c.getSuperclass()) {
            try {
                transformersField = c.getDeclaredField("transformers");
            } catch (NoSuchFieldException ignored) {
                // try superclass
            }
        }
        if (transformersField == null) {
            monitor.warning("Could not prepend PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer.");
            return;
        }
        transformersField.setAccessible(true);
        try {
            var list = (List<TypeTransformer<?, ?>>) transformersField.get(managementApiRegistry);
            list.removeIf(t -> t instanceof PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer);
            list.add(0, transformer);
            monitor.debug("Prepended PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer for management-api.");
        } catch (ReflectiveOperationException e) {
            monitor.warning("Could not prepend PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer: "
                    + e.getClass().getSimpleName());
        }
    }
}
