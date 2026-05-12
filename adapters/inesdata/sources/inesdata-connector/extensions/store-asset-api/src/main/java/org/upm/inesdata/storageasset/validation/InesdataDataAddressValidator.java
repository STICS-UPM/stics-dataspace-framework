package org.upm.inesdata.storageasset.validation;

import jakarta.json.JsonArray;
import jakarta.json.JsonObject;
import jakarta.json.JsonValue;
import org.eclipse.edc.spi.constants.CoreConstants;
import org.eclipse.edc.spi.types.domain.DataAddress;
import org.eclipse.edc.validator.spi.ValidationResult;
import org.eclipse.edc.validator.spi.Validator;
import org.eclipse.edc.validator.spi.Violation;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.eclipse.edc.validator.spi.Violation.violation;

/**
 * Extends the default DataAddress validation to allow the Kafka source used by
 * the EDC+Kafka validation suite while keeping explicit validation for the
 * supported INESData address types.
 */
public class InesdataDataAddressValidator {

    public static final String PROPERTY_NAME = CoreConstants.EDC_NAMESPACE + "name";
    public static final String PROPERTY_AMAZONS3_REGION = CoreConstants.EDC_NAMESPACE + "region";
    public static final String PROPERTY_AMAZONS3_BUCKET_NAME = CoreConstants.EDC_NAMESPACE + "bucketName";
    public static final String PROPERTY_AMAZONS3_ACCESS_KEY_ID = CoreConstants.EDC_NAMESPACE + "accessKeyId";
    public static final String PROPERTY_AMAZONS3_SECRET_ACCESS_KEY = CoreConstants.EDC_NAMESPACE + "secretAccessKey";
    public static final String PROPERTY_AMAZONS3_ENDPOINT_OVERRIDE = CoreConstants.EDC_NAMESPACE + "endpointOverride";
    public static final String PROPERTY_HTTP_DATA_BASE_URL = CoreConstants.EDC_NAMESPACE + "baseUrl";
    public static final String PROPERTY_KAFKA_TOPIC = CoreConstants.EDC_NAMESPACE + "topic";
    public static final String PROPERTY_KAFKA_BOOTSTRAP_SERVERS = CoreConstants.EDC_NAMESPACE + "kafka.bootstrap.servers";

    private InesdataDataAddressValidator() {
    }

    public static Validator<JsonObject> instance() {
        return new TypeBasedValidator();
    }

    private static class TypeBasedValidator implements Validator<JsonObject> {

        @Override
        public ValidationResult validate(JsonObject dataAddress) {
            String type = extractValueFromJsonArray(dataAddress, DataAddress.EDC_DATA_ADDRESS_TYPE_PROPERTY);

            if (type == null) {
                return ValidationResult.failure(violation(
                        "The 'https://w3id.org/edc/v0.0.1/ns/type' field is missing or invalid in dataAddress",
                        DataAddress.EDC_DATA_ADDRESS_TYPE_PROPERTY
                ));
            }

            return switch (type) {
                case "AmazonS3" -> validateAmazonS3(dataAddress);
                case "HttpData" -> validateHttpData(dataAddress);
                case "Kafka" -> validateKafka(dataAddress);
                case "InesDataStore" -> ValidationResult.success();
                default -> ValidationResult.failure(violation(
                        "The value for 'https://w3id.org/edc/v0.0.1/ns/type' field is not valid",
                        DataAddress.EDC_DATA_ADDRESS_TYPE_PROPERTY
                ));
            };
        }

        private ValidationResult validateAmazonS3(JsonObject dataAddress) {
            var violations = new ArrayList<Violation>();

            requireField(dataAddress, PROPERTY_AMAZONS3_REGION, "AmazonS3", violations);
            requireField(dataAddress, PROPERTY_AMAZONS3_BUCKET_NAME, "AmazonS3", violations);
            requireField(dataAddress, PROPERTY_AMAZONS3_ACCESS_KEY_ID, "AmazonS3", violations);
            requireField(dataAddress, PROPERTY_AMAZONS3_SECRET_ACCESS_KEY, "AmazonS3", violations);
            requireField(dataAddress, PROPERTY_AMAZONS3_ENDPOINT_OVERRIDE, "AmazonS3", violations);

            return violations.isEmpty() ? ValidationResult.success() : ValidationResult.failure(violations);
        }

        private ValidationResult validateHttpData(JsonObject dataAddress) {
            var violations = new ArrayList<Violation>();

            requireField(dataAddress, PROPERTY_NAME, "HttpData", violations);
            requireField(dataAddress, PROPERTY_HTTP_DATA_BASE_URL, "HttpData", violations);

            return violations.isEmpty() ? ValidationResult.success() : ValidationResult.failure(violations);
        }

        private ValidationResult validateKafka(JsonObject dataAddress) {
            var violations = new ArrayList<Violation>();

            requireField(dataAddress, PROPERTY_KAFKA_TOPIC, "Kafka", violations);
            requireField(dataAddress, PROPERTY_KAFKA_BOOTSTRAP_SERVERS, "Kafka", violations);

            return violations.isEmpty() ? ValidationResult.success() : ValidationResult.failure(violations);
        }

        private void requireField(JsonObject dataAddress, String field, String type, List<Violation> violations) {
            if (extractValueFromJsonArray(dataAddress, field) == null) {
                violations.add(violation(
                        "Field '%s' is required for %s DataAddress type".formatted(field, type),
                        field
                ));
            }
        }

        private String extractValueFromJsonArray(JsonObject jsonObject, String key) {
            return Optional.ofNullable(jsonObject.getJsonArray(key))
                    .filter(array -> !array.isEmpty())
                    .map(array -> array.getJsonObject(0))
                    .map(obj -> obj.getString(org.eclipse.edc.jsonld.spi.JsonLdKeywords.VALUE))
                    .filter(value -> !value.isBlank())
                    .orElse(null);
        }
    }
}
