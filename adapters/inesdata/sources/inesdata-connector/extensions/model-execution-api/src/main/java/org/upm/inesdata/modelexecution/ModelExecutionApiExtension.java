package org.upm.inesdata.modelexecution;

import org.eclipse.edc.api.auth.spi.AuthenticationRequestFilter;
import org.eclipse.edc.api.auth.spi.registry.ApiAuthenticationRegistry;
import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.runtime.metamodel.annotation.Setting;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.security.Vault;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;
import org.eclipse.edc.spi.types.TypeManager;
import org.eclipse.edc.web.spi.WebService;
import org.eclipse.edc.web.spi.configuration.ApiContext;
import org.upm.inesdata.modelexecution.controller.ModelExecutionApiController;

@Extension(value = ModelExecutionApiExtension.NAME)
public class ModelExecutionApiExtension implements ServiceExtension {
    public static final String NAME = "Model Execution API Extension";
    private static final String DEFAULT_MANAGEMENT_PATH = "/management";
    private static final String DEFAULT_MANAGEMENT_PORT = "19193";
    private static final String DEFAULT_PROTOCOL = "dataspace-protocol-http";
    private static final String DEFAULT_TRANSFER_TYPE = "HttpData-PULL";

    @Setting(value = "Internal base URL used by the model execution API to call the management API.",
            defaultValue = "http://localhost:" + DEFAULT_MANAGEMENT_PORT + DEFAULT_MANAGEMENT_PATH)
    private static final String MANAGEMENT_BASE_URL = "asset.infer.management.baseurl";

    @Setting(value = "Fallback connector id for transfer requests triggered by model execution.", defaultValue = "")
    private static final String DEFAULT_CONNECTOR_ID = "asset.infer.connector.id";

    @Setting(value = "Fallback counter party address for transfer requests triggered by model execution.", defaultValue = "")
    private static final String DEFAULT_COUNTER_PARTY_ADDRESS = "asset.infer.counterparty.address";

    @Setting(value = "Fallback protocol for transfer requests triggered by model execution.", defaultValue = DEFAULT_PROTOCOL)
    private static final String DEFAULT_EXECUTION_PROTOCOL = "asset.infer.protocol";

    @Setting(value = "Fallback transfer type for transfer requests triggered by model execution.", defaultValue = DEFAULT_TRANSFER_TYPE)
    private static final String DEFAULT_EXECUTION_TRANSFER_TYPE = "asset.infer.transfer.type";

    @Inject
    private WebService webService;

    @Inject
    private TypeManager typeManager;

    @Inject
    private Monitor monitor;

    @Inject
    private Vault vault;

    @Inject
    private ApiAuthenticationRegistry authenticationRegistry;

    @Override
    public String name() {
        return NAME;
    }

    @Override
    public void initialize(ServiceExtensionContext context) {
        var managementPort = context.getSetting("web.http.management.port", DEFAULT_MANAGEMENT_PORT);
        var managementPath = context.getSetting("web.http.management.path", DEFAULT_MANAGEMENT_PATH);
        var defaultManagementBaseUrl = "http://localhost:%s%s".formatted(managementPort, managementPath);
        var managementBaseUrl = context.getSetting(MANAGEMENT_BASE_URL, defaultManagementBaseUrl);
        var localParticipantId = context.getParticipantId();

        var authenticationFilter = new AuthenticationRequestFilter(authenticationRegistry, "management-api");
        webService.registerResource(ApiContext.MANAGEMENT, authenticationFilter);
        webService.registerResource(ApiContext.MANAGEMENT, new ModelExecutionApiController(
                typeManager,
                monitor,
                vault,
                managementBaseUrl,
                localParticipantId,
                context.getSetting(DEFAULT_CONNECTOR_ID, ""),
                context.getSetting(DEFAULT_COUNTER_PARTY_ADDRESS, ""),
                context.getSetting(DEFAULT_EXECUTION_PROTOCOL, DEFAULT_PROTOCOL),
                context.getSetting(DEFAULT_EXECUTION_TRANSFER_TYPE, DEFAULT_TRANSFER_TYPE)
        ));
    }
}
