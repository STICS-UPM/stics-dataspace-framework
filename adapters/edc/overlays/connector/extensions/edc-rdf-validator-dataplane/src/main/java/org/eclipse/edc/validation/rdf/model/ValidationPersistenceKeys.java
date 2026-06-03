package org.eclipse.edc.validation.rdf.model;

public final class ValidationPersistenceKeys {
    /** Current prefix for RDF validation keys in {@code edc_transfer_process.private_properties}. */
    public static final String KEY_PREFIX = "edc.rdf.validation.";
    /** Legacy prefix (read-only compatibility when loading Management API responses). */
    public static final String LEGACY_KEY_PREFIX = "inesdata.rdf.validation.";
    private static final String PREFIX = KEY_PREFIX;

    public static final String STATUS = PREFIX + "status";
    public static final String MESSAGE = PREFIX + "message";
    public static final String TRANSFER_ID = PREFIX + "transferId";
    public static final String ASSET_ID = PREFIX + "assetId";
    public static final String FORMAT = PREFIX + "format";
    public static final String ONTOLOGY_URL = PREFIX + "ontologyUrl";
    public static final String SHACL_URL = PREFIX + "shaclUrl";
    public static final String ERRORS = PREFIX + "errors";
    public static final String TIMESTAMP = PREFIX + "timestamp";

    private ValidationPersistenceKeys() {
    }
}
