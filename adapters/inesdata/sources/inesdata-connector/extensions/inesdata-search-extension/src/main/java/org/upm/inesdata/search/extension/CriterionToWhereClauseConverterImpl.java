/*
 *  Copyright (c) 2023 Bayerische Motoren Werke Aktiengesellschaft (BMW AG)
 *
 *  This program and the accompanying materials are made available under the
 *  terms of the Apache License, Version 2.0 which is available at
 *  https://www.apache.org/licenses/LICENSE-2.0
 *
 *  SPDX-License-Identifier: Apache-2.0
 *
 *  Contributors:
 *       Bayerische Motoren Werke Aktiengesellschaft (BMW AG) - initial API and implementation
 *
 */

package org.upm.inesdata.search.extension;

import org.eclipse.edc.spi.query.Criterion;
import org.eclipse.edc.sql.translation.CriterionToWhereClauseConverter;
import org.eclipse.edc.sql.translation.SqlOperatorTranslator;
import org.eclipse.edc.sql.translation.TranslationMapping;
import org.eclipse.edc.sql.translation.WhereClause;
import org.eclipse.edc.web.spi.exception.InvalidRequestException;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static java.util.Collections.unmodifiableCollection;

public class CriterionToWhereClauseConverterImpl implements CriterionToWhereClauseConverter {

    private static final String GENERIC_SEARCH = "genericSearch";
    private static final String ASSET_DATA_PROPERTY = "'https://w3id.org/edc/v0.0.1/ns/assetData'";
    private static final String ASSET_DATA_PROPERTY_KEY = "https://w3id.org/edc/v0.0.1/ns/assetData";
    private static final String[] MODEL_VOCABULARIES = {
            "JS_DAIMO_Model",
            "https://w3id.org/edc/v0.0.1/ns/JS_DAIMO_Model"
    };
    private static final String[] DATASET_VOCABULARIES = {
            "JS_DAIMO_Dataset",
            "https://w3id.org/edc/v0.0.1/ns/JS_DAIMO_Dataset"
    };
    private static final String[] ALL_DAIMO_VOCABULARIES = {
            "JS_DAIMO_Model",
            "https://w3id.org/edc/v0.0.1/ns/JS_DAIMO_Model",
            "JS_DAIMO_Dataset",
            "https://w3id.org/edc/v0.0.1/ns/JS_DAIMO_Dataset"
    };
    private static final Map<String, AliasFilter> DAIMO_ALIASES = buildAliases();
    private static final String [] COMMON_PROPERTIES = {
            "https://w3id.org/edc/v0.0.1/ns/id",
            "https://w3id.org/edc/v0.0.1/ns/name",
            "https://w3id.org/edc/v0.0.1/ns/version",
            "https://w3id.org/edc/v0.0.1/ns/contenttype",
            "http://purl.org/dc/terms/format",
            "http://www.w3.org/ns/dcat#keyword",
            "http://www.w3.org/ns/dcat#byteSize",
            "https://w3id.org/edc/v0.0.1/ns/shortDescription",
            "https://w3id.org/edc/v0.0.1/ns/assetType",
            "http://purl.org/dc/terms/description"
    };
    private final TranslationMapping translationMapping;
    private final SqlOperatorTranslator operatorTranslator;

    public CriterionToWhereClauseConverterImpl(TranslationMapping translationMapping, SqlOperatorTranslator operatorTranslator) {
        this.translationMapping = translationMapping;
        this.operatorTranslator = operatorTranslator;
    }

    @Override
    public WhereClause convert(Criterion criterion) {
        var operator = operatorTranslator.translate(criterion.getOperator().toLowerCase());
        if (operator == null) {
            throw new IllegalArgumentException("The operator '%s' is not supported".formatted(criterion.getOperator()));
        }

        if (!operator.rightOperandClass().isAssignableFrom(criterion.getOperandRight().getClass())) {
            throw new IllegalArgumentException("The operator '%s' requires the right-hand operand to be of type %s"
                    .formatted(criterion.getOperator(), operator.rightOperandClass().getSimpleName()));
        }

        var alias = DAIMO_ALIASES.get(criterion.getOperandLeft().toString());
        if (alias != null) {
            return generateAliasWhereClause(criterion, alias);
        } else if (criterion.getOperandLeft().toString().startsWith(ASSET_DATA_PROPERTY)) {
            return generateVocabularyWhereClause(criterion);
        } else if (GENERIC_SEARCH.equals(criterion.getOperandLeft().toString())) {
            return generateGenericPropertiesWhereClause(criterion);
        }

        var whereClause = translationMapping.getWhereClause(criterion, operator);
        if (whereClause == null) {
            return new WhereClause("0 = ?", 1);
        }

        return whereClause;
    }

    private static Map<String, AliasFilter> buildAliases() {
        var aliases = new LinkedHashMap<String, AliasFilter>();

        register(aliases, new AliasFilter(List.of("https://w3id.org/edc/v0.0.1/ns/assetType", "assetType"), List.of()),
                "daimo:assetType");
        register(aliases, new AliasFilter(
                        List.of("http://purl.org/dc/terms/format", "dct:format", "dcterms:format", "format"),
                        assetPaths(DATASET_VOCABULARIES, "http://purl.org/dc/terms/format", "dct:format", "dcterms:format", "format")),
                "daimo:format");
        register(aliases, new AliasFilter(List.of("https://w3id.org/edc/v0.0.1/ns/name", "name"), List.of()),
                "daimo:name");
        register(aliases, new AliasFilter(List.of("http://purl.org/dc/terms/description", "description"), List.of()),
                "daimo:description");
        register(aliases, new AliasFilter(
                        List.of("http://www.w3.org/ns/dcat#keyword", "keywords", "dcat:keyword"),
                        assetPaths(DATASET_VOCABULARIES, "http://www.w3.org/ns/dcat#keyword", "dcat:keyword", "keywords")),
                "daimo:keyword", "daimo:keywords");
        register(aliases, new AliasFilter(List.of(), List.of(), true), "daimo:search");

        register(aliases, new AliasFilter(List.of(), assetPaths(ALL_DAIMO_VOCABULARIES,
                        "taskCategory", "daimo:taskCategory", "https://w3id.org/pionera/daimo#taskCategory",
                        "taskCategory")),
                "daimo:taskCategory", "taskCategory");
        register(aliases, new AliasFilter(List.of(), assetPaths(ALL_DAIMO_VOCABULARIES,
                        "taskType", "daimo:taskType", "https://w3id.org/pionera/daimo#taskType",
                        "taskType")),
                "daimo:taskType", "taskType");
        register(aliases, new AliasFilter(List.of(), assetPaths(ALL_DAIMO_VOCABULARIES,
                        "modality", "daimo:modality", "https://w3id.org/pionera/daimo#modality",
                        "modality")),
                "daimo:modality", "modality");
        register(aliases, new AliasFilter(List.of(), assetPaths(ALL_DAIMO_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#subtask",
                        "subtask", "daimo:subtask")),
                "daimo:subtask", "subtask");
        register(aliases, new AliasFilter(List.of(), assetPaths(ALL_DAIMO_VOCABULARIES,
                        "subtaskDescription", "daimo:subtaskDescription",
                        "https://w3id.org/pionera/daimo#subtaskDescription")),
                "daimo:subtaskDescription", "subtaskDescription");
        register(aliases, new AliasFilter(List.of(), assetPaths(MODEL_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#endpointBehavior", "daimo:endpointBehavior",
                        "endpointBehavior")),
                "daimo:endpointBehavior", "endpointBehavior");
        register(aliases, new AliasFilter(List.of(), assetPaths(MODEL_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#requestShape", "daimo:requestShape",
                        "requestShape")),
                "daimo:requestShape", "requestShape");
        register(aliases, new AliasFilter(List.of(), assetPaths(MODEL_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#inputSchema", "inputSchema", "daimo:inputSchema")),
                "daimo:inputSchema", "inputSchema");
        register(aliases, new AliasFilter(List.of(), assetPaths(MODEL_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#inputExample", "inputExample", "daimo:inputExample")),
                "daimo:inputExample", "inputExample");
        register(aliases, new AliasFilter(List.of(), assetPaths(MODEL_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#metrics", "metrics", "daimo:metrics")),
                "daimo:metrics", "metrics");
        register(aliases, new AliasFilter(List.of(), assetPaths(MODEL_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#libraryName", "daimo:libraryName",
                        "libraryName")),
                "daimo:libraryName", "libraryName");
        register(aliases, new AliasFilter(
                        List.of("http://purl.org/dc/terms/language", "dct:language", "dcterms:language", "language"),
                        assetPaths(ALL_DAIMO_VOCABULARIES,
                                "http://purl.org/dc/terms/language", "dct:language", "dcterms:language", "language")),
                "daimo:language", "dct:language", "dcterms:language", "language");
        register(aliases, new AliasFilter(
                        List.of("http://purl.org/dc/terms/license", "dct:license", "dcterms:license", "license"),
                        assetPaths(ALL_DAIMO_VOCABULARIES,
                                "http://purl.org/dc/terms/license", "dct:license", "dcterms:license", "license")),
                "daimo:license", "dct:license", "dcterms:license", "license");

        register(aliases, new AliasFilter(List.of(), assetPaths(DATASET_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#input", "input", "daimo:input")),
                "daimo:input", "input");
        register(aliases, new AliasFilter(List.of(), assetPaths(DATASET_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#label", "label", "daimo:label")),
                "daimo:label", "label");
        register(aliases, new AliasFilter(List.of(), assetPaths(DATASET_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#labelType", "labelType", "daimo:labelType")),
                "daimo:labelType", "labelType");
        register(aliases, new AliasFilter(List.of(), assetPaths(DATASET_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#datasetVersion", "datasetVersion", "daimo:datasetVersion")),
                "daimo:datasetVersion", "datasetVersion");
        register(aliases, new AliasFilter(List.of(), assetPaths(DATASET_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#datasetRole", "datasetRole", "daimo:datasetRole")),
                "daimo:datasetRole", "datasetRole");
        register(aliases, new AliasFilter(List.of(), assetPaths(DATASET_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#protocol", "protocol", "daimo:protocol")),
                "daimo:protocol", "protocol");
        register(aliases, new AliasFilter(List.of(), assetPaths(DATASET_VOCABULARIES,
                        "https://w3id.org/pionera/daimo#randomSeed", "randomSeed", "daimo:randomSeed")),
                "daimo:randomSeed", "randomSeed");

        return Map.copyOf(aliases);
    }

    private static void register(Map<String, AliasFilter> aliases, AliasFilter filter, String... keys) {
        for (String key : keys) {
            aliases.put(key, filter);
        }
    }

    private static List<AssetDataPath> assetPaths(String[] vocabularies, String... fields) {
        var result = new ArrayList<AssetDataPath>();
        for (String vocabulary : vocabularies) {
            for (String field : fields) {
                result.add(new AssetDataPath(vocabulary, field));
            }
        }
        return result;
    }

    private WhereClause generateAliasWhereClause(Criterion criterion, AliasFilter alias) {
        var operator = criterion.getOperator().toUpperCase(Locale.ROOT);
        var values = splitOperandValues(criterion.getOperandRight().toString());
        if (values.isEmpty()) {
            return new WhereClause("0 = ?", 1);
        }

        var params = new ArrayList<String>();
        var clauses = new ArrayList<String>();

        if (alias.includeRawProperties()) {
            clauses.add(buildTextPredicate("properties::text", operator, values, params));
        }

        for (String property : alias.properties()) {
            clauses.add(buildTextPredicate("properties ->> '" + property + "'", operator, values, params));
        }

        for (AssetDataPath path : alias.assetDataPaths()) {
            clauses.add(buildAssetDataPredicate(path, operator, values, params));
        }

        if (clauses.isEmpty()) {
            return new WhereClause("0 = ?", 1);
        }

        return new WhereClause("(" + String.join(" OR ", clauses) + ")", unmodifiableCollection(params));
    }

    private String buildAssetDataPredicate(AssetDataPath path, String operator, List<String> values, List<String> params) {
        var valueExpression = "COALESCE(value ->> '@value', value ->> '@id', value #>> '{}')";
        return """
                EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(
                        CASE
                            WHEN jsonb_typeof(properties::jsonb -> '%s' -> '%s') = 'array'
                                THEN properties::jsonb -> '%s' -> '%s'
                            WHEN properties::jsonb -> '%s' -> '%s' IS NULL
                                THEN '[]'::jsonb
                            ELSE jsonb_build_array(properties::jsonb -> '%s' -> '%s')
                        END
                    ) AS vocab
                    CROSS JOIN LATERAL jsonb_array_elements(
                        CASE
                            WHEN jsonb_typeof(vocab -> '%s') = 'array'
                                THEN vocab -> '%s'
                            WHEN vocab -> '%s' IS NULL
                                THEN '[]'::jsonb
                            ELSE jsonb_build_array(vocab -> '%s')
                        END
                    ) AS value
                    WHERE %s
                )
                """.formatted(
                ASSET_DATA_PROPERTY_KEY, path.vocabulary(),
                ASSET_DATA_PROPERTY_KEY, path.vocabulary(),
                ASSET_DATA_PROPERTY_KEY, path.vocabulary(),
                ASSET_DATA_PROPERTY_KEY, path.vocabulary(),
                path.field(), path.field(), path.field(), path.field(),
                buildTextPredicate(valueExpression, operator, values, params)
        );
    }

    private String buildTextPredicate(String valueExpression, String operator, List<String> values, List<String> params) {
        var comparisons = new ArrayList<String>();
        for (String value : values) {
            switch (operator) {
                case "LIKE" -> {
                    comparisons.add(valueExpression + " ILIKE ?");
                    params.add(value);
                }
                case ">", ">=", "<", "<=" -> {
                    var numericComparison = "(" + valueExpression + " ~ '^-?[0-9]+(\\.[0-9]+)?$' AND ("
                            + valueExpression + ")::double precision " + operator + " ?::double precision)";
                    comparisons.add(numericComparison);
                    params.add(value);
                }
                case "=" -> {
                    comparisons.add("LOWER(" + valueExpression + ") = LOWER(?)");
                    params.add(value);
                }
                default -> throw new IllegalArgumentException(
                        "The operator '%s' is not supported for DAIMO alias filters".formatted(operator));
            }
        }
        return "(" + String.join(" OR ", comparisons) + ")";
    }

    private List<String> splitOperandValues(String raw) {
        if (raw == null) {
            return List.of();
        }
        var result = new ArrayList<String>();
        for (String value : raw.split(",")) {
            var trimmed = value.trim();
            if (!trimmed.isEmpty()) {
                result.add(trimmed);
            }
        }
        return result;
    }

    private WhereClause generateGenericPropertiesWhereClause(Criterion criterion) {
        String operator = criterion.getOperator();
        String rightValue = criterion.getOperandRight().toString();
        List<String> values = new ArrayList<>(Collections.nCopies(COMMON_PROPERTIES.length, rightValue));

        StringBuilder sqlWhereBuilder = new StringBuilder("(");
        for (int i = 0; i < COMMON_PROPERTIES.length; i++) {
            sqlWhereBuilder.append("properties ->> '")
                    .append(COMMON_PROPERTIES[i])
                    .append("' ")
                    .append(operator)
                    .append(" ?");
            if (i < COMMON_PROPERTIES.length - 1) {
                sqlWhereBuilder.append(" OR ");
            }
        }
        sqlWhereBuilder.append(")");

        return new WhereClause(sqlWhereBuilder.toString(), unmodifiableCollection(values));
    }

    private WhereClause generateVocabularyWhereClause(Criterion criterion) {
        String[] propertiesList = splitByDotOutsideQuotes(criterion.getOperandLeft().toString());
        StringBuilder sqlWhereBuilder = new StringBuilder();

        switch (propertiesList.length) {
            case 3 ->
                    generateNonObjectPropertySQL(sqlWhereBuilder, propertiesList, criterion.getOperandRight().toString(), false);
            case 4 -> {
                if  (propertiesList[3].equals("'@id'")) {
                    generateNonObjectPropertySQL(sqlWhereBuilder, propertiesList, criterion.getOperandRight().toString(), true);
                } else {
                    generateObjectPropertySQL(sqlWhereBuilder, propertiesList, criterion.getOperandRight().toString());
                }

            }

            default -> throw new InvalidRequestException("Invalid vocabulary argument in the operandLeft: %s"
                    .formatted(criterion.getOperandLeft().toString()));
        }

        return new WhereClause(sqlWhereBuilder.toString(), unmodifiableCollection(new ArrayList<>()));
    }

    private void generateObjectPropertySQL(StringBuilder sqlWhereBuilder, String[] propertiesList, String operandRight) {
        sqlWhereBuilder.append("EXISTS (SELECT 1 FROM jsonb_array_elements((properties::jsonb -> ")
                .append(propertiesList[0])
                .append(" -> ")
                .append(propertiesList[1])
                .append(")::jsonb) AS vocab WHERE vocab -> ")
                .append(propertiesList[2])
                .append(" @> '[{")
                .append(propertiesList[3].replaceAll("'", "\""))
                .append(": [{\"@value\": \"")
                .append(operandRight)
                .append("\"}]}]')");
    }

    private void generateNonObjectPropertySQL(StringBuilder sqlWhereBuilder, String[] propertiesList, String operandRight, boolean isIdProperty) {
        sqlWhereBuilder.append("(properties::jsonb -> ")
                .append(propertiesList[0])
                .append(" -> ")
                .append(propertiesList[1])
                .append(")::jsonb @> '[{")
                .append(propertiesList[2].replaceAll("'", "\""))
                .append(isIdProperty ? ": [{\"@id\": \"" : ": [{\"@value\": \"")
                .append(operandRight)
                .append("\"}]}]'::jsonb");
    }

    private String[] splitByDotOutsideQuotes(String input) {
        List<String> parts = new ArrayList<>();

        Pattern pattern = Pattern.compile("\\.(?=(?:[^']*'[^']*')*[^']*$)");

        Matcher matcher = pattern.matcher(input);
        int start = 0;

        while (matcher.find()) {
            String part = input.substring(start, matcher.start()).trim();
            parts.add(part);
            start = matcher.end();
        }

        if (start < input.length()) {
            String lastPart = input.substring(start).trim();
            parts.add(lastPart);
        }

        return parts.toArray(new String[0]);
    }

    private record AliasFilter(List<String> properties, List<AssetDataPath> assetDataPaths, boolean includeRawProperties) {
        private AliasFilter(List<String> properties, List<AssetDataPath> assetDataPaths) {
            this(properties, assetDataPaths, false);
        }
    }

    private record AssetDataPath(String vocabulary, String field) {
    }
}
