package org.upm.inesdata.validator;

import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;
import org.eclipse.edc.web.spi.WebService;
import org.upm.inesdata.validator.controller.AssetRdfValidationApiController;
import org.upm.inesdata.validator.services.RdfValidationService;
import org.upm.inesdata.validator.services.impl.JenaValidationService;

@Extension(OntologyValidatorExtension.NAME)
public class OntologyValidatorExtension implements ServiceExtension {

    public static final String NAME = "Ontology Validator Extension";

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

        monitor.info("🔥 OntologyValidatorExtension initialized!");
    }
}