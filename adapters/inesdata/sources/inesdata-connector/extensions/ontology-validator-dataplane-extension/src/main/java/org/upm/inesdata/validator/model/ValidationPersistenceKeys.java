package org.upm.inesdata.validator.model;

public final class ValidationPersistenceKeys {
    /** Prefix for keys merged into {@code edc_transfer_process.private_properties}. */
    public static final String KEY_PREFIX = "inesdata.rdf.validation.";
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
