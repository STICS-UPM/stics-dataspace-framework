package org.upm.inesdata.validator.services;

import org.eclipse.edc.validator.spi.ValidationResult;

import java.io.InputStream;

import org.upm.inesdata.validator.services.enums.RdfFormat;

public interface RdfValidationService {

    ValidationResult validate(
            InputStream rdfStream,
            RdfFormat format,
            String ontologyUrl,
            String shaclUrl
    );
}
