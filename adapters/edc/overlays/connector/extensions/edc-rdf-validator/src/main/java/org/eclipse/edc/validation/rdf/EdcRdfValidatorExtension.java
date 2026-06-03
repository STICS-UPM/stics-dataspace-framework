package org.eclipse.edc.validation.rdf;

import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;
import org.eclipse.edc.web.spi.WebService;
import org.eclipse.edc.validation.rdf.controller.AssetRdfValidationApiController;
import org.eclipse.edc.validation.rdf.services.RdfValidationService;
import org.eclipse.edc.validation.rdf.services.impl.JenaValidationService;

@Extension(EdcRdfValidatorExtension.NAME)
public class EdcRdfValidatorExtension implements ServiceExtension {

    public static final String NAME = "EDC RDF Validator Extension";

    @Inject
    private WebService webService;

    @Inject
    private Monitor monitor;

    @Override
    public void initialize(ServiceExtensionContext context) {

        RdfValidationService validationService = new JenaValidationService();
        context.registerService(RdfValidationService.class, validationService);

        var controller = new AssetRdfValidationApiController(validationService);

        webService.registerResource("management", controller);

        monitor.info("🔥 EdcRdfValidatorExtension initialized!");
    }
}