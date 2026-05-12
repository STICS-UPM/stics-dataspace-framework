package org.upm.inesdata.validator.services.enums;

public enum RdfFormat {

    TURTLE("text/turtle"),
    RDFXML("application/rdf+xml"),
    JSONLD("application/ld+json"),
    NTRIPLES("application/n-triples"),
    N3("text/n3");

    private final String mimeType;

    RdfFormat(String mimeType) {
        this.mimeType = mimeType;
    }

    public String getMimeType() {
        return mimeType;
    }

    public static RdfFormat fromMimeType(String mimeType) {
        if (mimeType == null) {
            throw new IllegalArgumentException("mimeType is null");
        }

        for (RdfFormat format : values()) {
            if (mimeType.startsWith(format.mimeType)) {
                return format;
            }
        }

        throw new IllegalArgumentException("Unsupported RDF mime type: " + mimeType);
    }

    public static RdfFormat fromInput(String input) {
        if (input == null || input.isBlank()) {
            throw new IllegalArgumentException("format is null or empty");
        }

        var normalized = input.trim().toLowerCase();

        return switch (normalized) {
            case "turtle", "ttl", "text/turtle" -> TURTLE;
            case "rdfxml", "rdf/xml", "application/rdf+xml" -> RDFXML;
            case "jsonld", "json-ld", "application/ld+json" -> JSONLD;
            case "ntriples", "n-triples", "nt", "application/n-triples" -> NTRIPLES;
            case "n3", "notation3", "text/n3" -> N3;
            default -> throw new IllegalArgumentException("Unsupported RDF format: " + input);
        };
    }
}