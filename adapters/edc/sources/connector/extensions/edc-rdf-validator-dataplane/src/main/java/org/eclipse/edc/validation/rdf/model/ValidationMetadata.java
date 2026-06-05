package org.eclipse.edc.validation.rdf.model;

public class ValidationMetadata {
    public final String ontologyUrl;
    public final String shaclUrl;

    public ValidationMetadata(String ontologyUrl, String shaclUrl) {
        this.ontologyUrl = ontologyUrl;
        this.shaclUrl = shaclUrl;
    }
}
