package org.eclipse.edc.validation.rdf;

import org.eclipse.edc.connector.controlplane.services.spi.asset.AssetService;
import org.eclipse.edc.connector.controlplane.transfer.spi.store.TransferProcessStore;
import org.eclipse.edc.connector.dataplane.spi.pipeline.DataSinkFactory;
import org.eclipse.edc.connector.dataplane.spi.pipeline.PipelineService;
import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.spi.event.Event;
import org.eclipse.edc.spi.event.EventRouter;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;
import org.eclipse.edc.transaction.datasource.spi.DataSourceRegistry;
import org.eclipse.edc.transaction.spi.TransactionContext;
import org.eclipse.edc.web.spi.WebService;
import org.eclipse.edc.validation.rdf.controller.RdfValidationCallbackController;
import org.eclipse.edc.validation.rdf.fallback.AutomaticRdfValidationSubscriber;
import org.eclipse.edc.validation.rdf.persistence.TransferProcessValidationPersistence;
import org.eclipse.edc.validation.rdf.pipeline.ValidatingDataSinkFactory;
import org.eclipse.edc.validation.rdf.services.RdfValidationService;

import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

@Extension(EdcRdfValidatorDataplaneExtension.NAME)
public class EdcRdfValidatorDataplaneExtension implements ServiceExtension {
    public static final String NAME = "EDC RDF Validator Dataplane Extension";

    @Inject
    private Monitor monitor;
    @Inject
    private WebService webService;
    @Inject
    private EventRouter eventRouter;
    @Inject
    private TransferProcessStore transferProcessStore;
    @Inject
    private AssetService assetService;
    @Inject
    private PipelineService pipelineService;
    @Inject
    private DataSourceRegistry dataSourceRegistry;
    @Inject
    private TransactionContext transactionContext;

    private ServiceExtensionContext context;
    private RdfValidationService validationService;
    private String runtimeParticipantId;
    private TransferProcessValidationPersistence validationPersistence;
    private final Set<String> inStreamValidatedTransfers = ConcurrentHashMap.newKeySet();

    @Override
    public void initialize(ServiceExtensionContext context) {
        this.context = context;
        this.runtimeParticipantId = context.getParticipantId();

        this.validationPersistence = new TransferProcessValidationPersistence(
                dataSourceRegistry, transactionContext, monitor, DataSourceRegistry.DEFAULT_DATASOURCE);

        var subscriber = new AutomaticRdfValidationSubscriber(
                this::getRdfValidationService,
                monitor,
                transferProcessStore,
                assetService,
                inStreamValidatedTransfers,
                validationPersistence
        );
        eventRouter.register(Event.class, subscriber);
        monitor.info("EDC RDF Validator Dataplane Extension initialized");
    }

    @Override
    public void prepare() {
        decoratePipelineSinkFactories();
    }

    @Override
    public void start() {
        var service = getRdfValidationService();
        if (service == null) {
            monitor.warning("RdfValidationService not found. Callback endpoint will not be registered.");
            return;
        }

        var controller = new RdfValidationCallbackController(service, monitor);
        webService.registerResource("public", controller);
        monitor.info("EDC RDF Validator Dataplane Extension started - callback endpoint available at /public/validation/rdf");
    }

    private RdfValidationService getRdfValidationService() {
        if (validationService == null) {
            try {
                validationService = context.getService(RdfValidationService.class);
            } catch (Exception e) {
                monitor.debug("RdfValidationService not yet available: " + e.getMessage());
                return null;
            }
        }
        return validationService;
    }

    @SuppressWarnings("unchecked")
    private void decoratePipelineSinkFactories() {
        try {
            var sinkFactoriesField = pipelineService.getClass().getDeclaredField("sinkFactories");
            sinkFactoriesField.setAccessible(true);
            var sinkFactories = (List<DataSinkFactory>) sinkFactoriesField.get(pipelineService);

            var wrappedCount = 0;
            for (var idx = 0; idx < sinkFactories.size(); idx++) {
                var currentFactory = sinkFactories.get(idx);
                if (currentFactory instanceof ValidatingDataSinkFactory) {
                    continue;
                }
                sinkFactories.set(idx, new ValidatingDataSinkFactory(
                        currentFactory,
                        this::getRdfValidationService,
                        monitor,
                        assetService,
                        transferProcessStore,
                        runtimeParticipantId,
                        inStreamValidatedTransfers,
                        validationPersistence
                ));
                wrappedCount++;
            }

            monitor.info("RDF in-stream validation enabled: wrapped " + wrappedCount + " dataplane sink factory(ies).");
        } catch (NoSuchFieldException | IllegalAccessException e) {
            monitor.warning("Unable to decorate dataplane sink factories for in-stream RDF validation: " + e.getMessage());
        }
    }
}