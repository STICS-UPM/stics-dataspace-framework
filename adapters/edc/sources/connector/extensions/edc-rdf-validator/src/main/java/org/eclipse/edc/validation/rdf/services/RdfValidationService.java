package org.eclipse.edc.validation.rdf.services;

import org.eclipse.edc.validator.spi.ValidationResult;

import java.io.InputStream;

import org.eclipse.edc.validation.rdf.services.enums.RdfFormat;

public interface RdfValidationService {

    ValidationResult validate(
            InputStream rdfStream,
            RdfFormat format,
            String ontologyUrl,
            String shaclUrl
    );
}
