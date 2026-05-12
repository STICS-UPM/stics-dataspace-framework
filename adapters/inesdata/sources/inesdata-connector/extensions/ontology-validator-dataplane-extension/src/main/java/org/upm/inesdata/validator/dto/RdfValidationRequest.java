package org.upm.inesdata.validator.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Request DTO for RDF validation callback.
 *
 * Example:
 * {
 *   "transferId": "transfer-123",
 *   "rdfContent": "base64-encoded content",
 *   "format": "TURTLE",
 *   "ontologyUrl": "http://ontology-hub:3333/ontologies/example.n3",
 *   "shaclUrl": "http://ontology-hub:3333/shacl/example.ttl"
 * }
 */
public class RdfValidationRequest {

    @JsonProperty("transferId")
    private String transferId;

    @JsonProperty("rdfContent")
    private String rdfContent;

    @JsonProperty("format")
    private String format;

    @JsonProperty("ontologyUrl")
    private String ontologyUrl;

    @JsonProperty("shaclUrl")
    private String shaclUrl;

    public RdfValidationRequest() {
    }

    public RdfValidationRequest(
            String transferId,
            String rdfContent,
            String format,
            String ontologyUrl,
            String shaclUrl
    ) {
        this.transferId = transferId;
        this.rdfContent = rdfContent;
        this.format = format;
        this.ontologyUrl = ontologyUrl;
        this.shaclUrl = shaclUrl;
    }

    public String getTransferId() {
        return transferId;
    }

    public void setTransferId(String transferId) {
        this.transferId = transferId;
    }

    public String getRdfContent() {
        return rdfContent;
    }

    public void setRdfContent(String rdfContent) {
        this.rdfContent = rdfContent;
    }

    public String getFormat() {
        return format;
    }

    public void setFormat(String format) {
        this.format = format;
    }

    public String getOntologyUrl() {
        return ontologyUrl;
    }

    public void setOntologyUrl(String ontologyUrl) {
        this.ontologyUrl = ontologyUrl;
    }

    public String getShaclUrl() {
        return shaclUrl;
    }

    public void setShaclUrl(String shaclUrl) {
        this.shaclUrl = shaclUrl;
    }
}

