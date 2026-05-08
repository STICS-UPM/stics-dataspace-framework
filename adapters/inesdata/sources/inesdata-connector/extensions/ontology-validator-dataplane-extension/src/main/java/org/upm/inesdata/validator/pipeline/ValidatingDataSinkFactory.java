package org.upm.inesdata.validator.pipeline;

import org.eclipse.edc.connector.controlplane.services.spi.asset.AssetService;
import org.eclipse.edc.connector.controlplane.transfer.spi.store.TransferProcessStore;
import org.eclipse.edc.connector.dataplane.spi.pipeline.DataSink;
import org.eclipse.edc.connector.dataplane.spi.pipeline.DataSinkFactory;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.result.Result;
import org.eclipse.edc.spi.types.domain.transfer.DataFlowStartMessage;
import org.upm.inesdata.validator.persistence.TransferProcessValidationPersistence;
import org.upm.inesdata.validator.services.RdfValidationService;

import java.util.Set;
import java.util.function.Supplier;

public class ValidatingDataSinkFactory implements DataSinkFactory {
    private final DataSinkFactory delegate;
    private final Supplier<RdfValidationService> validationServiceProvider;
    private final Monitor monitor;
    private final AssetService assetService;
    private final TransferProcessStore transferProcessStore;
    private final String runtimeParticipantId;
    private final Set<String> alreadyValidatedTransfers;
    private final TransferProcessValidationPersistence persistence;

    public ValidatingDataSinkFactory(
            DataSinkFactory delegate,
            Supplier<RdfValidationService> validationServiceProvider,
            Monitor monitor,
            AssetService assetService,
            TransferProcessStore transferProcessStore,
            String runtimeParticipantId,
            Set<String> alreadyValidatedTransfers,
            TransferProcessValidationPersistence persistence
    ) {
        this.delegate = delegate;
        this.validationServiceProvider = validationServiceProvider;
        this.monitor = monitor;
        this.assetService = assetService;
        this.transferProcessStore = transferProcessStore;
        this.runtimeParticipantId = runtimeParticipantId;
        this.alreadyValidatedTransfers = alreadyValidatedTransfers;
        this.persistence = persistence;
    }

    @Override
    public String supportedType() {
        return delegate.supportedType();
    }

    @Override
    public DataSink createSink(DataFlowStartMessage request) {
        return new ValidatingDataSink(
                delegate.createSink(request),
                request,
                validationServiceProvider,
                monitor,
                assetService,
                transferProcessStore,
                runtimeParticipantId,
                alreadyValidatedTransfers,
                persistence
        );
    }

    @Override
    public Result<Void> validateRequest(DataFlowStartMessage request) {
        return delegate.validateRequest(request);
    }
}
