package org.upm.inesdata.inesdatatransfer;

import jakarta.json.Json;
import jakarta.json.JsonBuilderFactory;
import jakarta.json.JsonObject;
import org.eclipse.edc.connector.controlplane.transfer.spi.types.TransferProcess;
import org.upm.inesdata.inesdatatransfer.transform.PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer;
import org.eclipse.edc.connector.controlplane.api.management.transferprocess.transform.JsonObjectFromTransferStateTransformer;
import org.eclipse.edc.connector.controlplane.api.management.transferprocess.transform.JsonObjectToSuspendTransferTransformer;
import org.eclipse.edc.connector.controlplane.api.management.transferprocess.transform.JsonObjectToTerminateTransferTransformer;
import org.eclipse.edc.connector.controlplane.api.management.transferprocess.transform.JsonObjectToTransferRequestTransformer;
import org.eclipse.edc.connector.controlplane.api.management.transferprocess.validation.TerminateTransferValidator;
import org.eclipse.edc.connector.controlplane.services.spi.transferprocess.TransferProcessService;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.connector.controlplane.transfer.spi.store.TransferProcessStore;
import org.eclipse.edc.spi.security.Vault;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;
import org.eclipse.edc.transaction.datasource.spi.DataSourceRegistry;
import org.eclipse.edc.transaction.spi.TransactionContext;
import org.eclipse.edc.transform.spi.TypeTransformerRegistry;
import org.eclipse.edc.validator.spi.JsonObjectValidatorRegistry;
import org.eclipse.edc.web.spi.WebService;
import org.upm.inesdata.inesdatatransfer.controller.InesdataTransferProcessApiController;
import org.upm.inesdata.inesdatatransfer.controller.RdfValidationMirrorController;
import org.upm.inesdata.inesdatatransfer.validations.InesdataTransferRequestValidator;
import org.upm.inesdata.validator.persistence.TransferProcessValidationPersistence;
import org.eclipse.edc.transform.spi.TypeTransformer;

import java.lang.reflect.Field;
import java.util.Collections;
import java.util.List;

@Extension("Management API: Inesdata Transfer Process")
public class InesdataTransferProcessApiExtension implements ServiceExtension {
    public static final String NAME = "Management API: Transfer Process";
    public static final String DEFAULT_VALUE = "";
    public static final String AWS_ACCESS_KEY = "edc.aws.access.key";
    public static final String AWS_SECRET_ACCESS = "edc.aws.secret.access.key";
    public static final String AWS_ENDPOINT_OVERRIDE = "edc.aws.endpoint.override";
    public static final String AWS_REGION = "edc.aws.region";
    public static final String AWS_BUCKET_NAME = "edc.aws.bucket.name";


    @Inject
    private WebService webService;
    @Inject
    private TypeTransformerRegistry transformerRegistry;
    @Inject
    private TransferProcessService service;
    @Inject
    private JsonObjectValidatorRegistry validatorRegistry;
    @Inject
    private Vault vault;
    @Inject
    private TransferProcessStore transferProcessStore;
    @Inject
    private DataSourceRegistry dataSourceRegistry;
    @Inject
    private TransactionContext transactionContext;
    @Inject
    private Monitor monitor;

    private JsonBuilderFactory managementApiJsonBuilderFactory;
    private TransferProcessValidationPersistence validationPersistence;

    public InesdataTransferProcessApiExtension() {
    }

    public String name() {
        return "Management API: Inesdata Transfer Process";
    }

    public void initialize(ServiceExtensionContext context) {
        this.managementApiJsonBuilderFactory = Json.createBuilderFactory(Collections.emptyMap());
        TypeTransformerRegistry managementApiTransformerRegistry = this.transformerRegistry.forContext("management-api");
        managementApiTransformerRegistry.register(new JsonObjectFromTransferStateTransformer(this.managementApiJsonBuilderFactory));
        managementApiTransformerRegistry.register(new JsonObjectToTerminateTransferTransformer());
        managementApiTransformerRegistry.register(new JsonObjectToSuspendTransferTransformer());
        managementApiTransformerRegistry.register(new JsonObjectToTransferRequestTransformer());
        // Leer las variables de entorno
        var accessKey = vault.resolveSecret(context.getSetting(AWS_ACCESS_KEY, DEFAULT_VALUE));
        var secretKey = vault.resolveSecret(context.getSetting(AWS_SECRET_ACCESS, DEFAULT_VALUE));
        var endpointOverride = context.getSetting(AWS_ENDPOINT_OVERRIDE, DEFAULT_VALUE);
        var regionName = context.getSetting(AWS_REGION, DEFAULT_VALUE);
        var bucketName = context.getSetting(AWS_BUCKET_NAME, DEFAULT_VALUE);

        this.validatorRegistry.register("https://w3id.org/edc/v0.0.1/ns/TransferRequest", InesdataTransferRequestValidator.instance(context.getMonitor()));
        this.validatorRegistry.register("https://w3id.org/edc/v0.0.1/ns/TerminateTransfer", TerminateTransferValidator.instance());
        this.webService.registerResource(
                "management",
                new InesdataTransferProcessApiController(
                        context.getMonitor(),
                        this.service,
                        managementApiTransformerRegistry,
                        this.validatorRegistry,
                        bucketName,
                        regionName,
                        accessKey,
                        secretKey,
                        endpointOverride
                )
        );
        this.validationPersistence = new TransferProcessValidationPersistence(
                this.dataSourceRegistry, this.transactionContext, context.getMonitor(), DataSourceRegistry.DEFAULT_DATASOURCE);
        // Registered in the "public" web context (no auth filter): the provider data plane posts here
        // from another participant runtime, and any 4xx would be interpreted as a callback failure.
        // Validation is informational, so this endpoint must remain reachable without management credentials.
        this.webService.registerResource("public",
                new RdfValidationMirrorController(this.validationPersistence, context.getMonitor()));
    }

    /**
     * EDC's {@link TypeTransformerRegistry#transformerFor} streams the transformer list and
     * {@code findAny()} picks the first match. The stock {@code JsonObjectFromTransferProcessTransformer} is registered in
     * {@code TransferProcessApiExtension#initialize}, always before this extension's lifecycle order, so appending
     * our transformer in {@code start()} never wins. Prepend ours at index 0 via reflection on
     * {@code TypeTransformerRegistryImpl}'s {@code transformers} list.
     * <p>
     * The stock {@code JsonObjectFromTransferProcessTransformer} is left registered after ours: {@code findAny()}
     * still selects our transformer first, and removing the stock entry risked brittle side effects on the shared registry.
     */
    @Override
    public void start() {
        prependPrivatePropertiesTransformer(
                this.transformerRegistry.forContext("management-api"),
                new PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer(this.managementApiJsonBuilderFactory,
                        this.monitor, this.validationPersistence));
    }

    @SuppressWarnings({ "unchecked", "rawtypes" })
    private void prependPrivatePropertiesTransformer(org.eclipse.edc.transform.spi.TypeTransformerRegistry managementApiRegistry,
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
            monitor.warning(
                    "Could not prepend PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer: "
                            + "no 'transformers' field on " + managementApiRegistry.getClass().getName()
                            + ". TransferProcess JSON will omit privateProperties.");
            return;
        }
        transformersField.setAccessible(true);
        try {
            var list = (List<TypeTransformer<?, ?>>) transformersField.get(managementApiRegistry);
            list.removeIf(t -> t instanceof PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer);
            list.add(0, transformer);
            monitor.info("Prepended PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer for management-api "
                    + "(TransferProcess -> JsonObject exposes privateProperties; stock transformer remains as fallback).");

            var remaining = list.stream()
                    .filter(t -> t.getInputType() == TransferProcess.class && t.getOutputType() == JsonObject.class)
                    .map(t -> t.getClass().getName())
                    .toList();
            monitor.info("management-api TransferProcess->JsonObject transformers (in order): " + remaining);
        } catch (ReflectiveOperationException e) {
            monitor.warning("Could not prepend PrivatePropertiesIncludingJsonObjectFromTransferProcessTransformer: "
                    + e.getClass().getSimpleName() + (e.getMessage() != null ? (": " + e.getMessage()) : ""));
        }
    }
}
