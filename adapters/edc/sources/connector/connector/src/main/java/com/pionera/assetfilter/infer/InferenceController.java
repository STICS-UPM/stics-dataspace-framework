/*
 *  Copyright (c) 2026 Pionera
 *
 *  This program and the accompanying materials are made available under the
 *  terms of the Apache License, Version 2.0 which is available at
 *  https://www.apache.org/licenses/LICENSE-2.0
 *
 *  SPDX-License-Identifier: Apache-2.0
 *
 *  Contributors:
 *       Pionera - initial API and implementation
 *
 */

package com.pionera.assetfilter.infer;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.types.TypeManager;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import static jakarta.ws.rs.core.HttpHeaders.ACCEPT;
import static jakarta.ws.rs.core.HttpHeaders.AUTHORIZATION;
import static jakarta.ws.rs.core.HttpHeaders.CONTENT_TYPE;

@Path("/infer")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
public class InferenceController {

    private final ObjectMapper mapper;
    private final String managementBaseUrl;
    private final String localParticipantId;
    private final String defaultConnectorId;
    private final String defaultCounterPartyAddress;
    private final String defaultProtocol;
    private final String defaultTransferType;
    private final Monitor monitor;
    private final HttpClient httpClient = HttpClient.newHttpClient();

    public InferenceController(TypeManager typeManager,
                               String managementBaseUrl,
                               String localParticipantId,
                               String defaultConnectorId,
                               String defaultCounterPartyAddress,
                               String defaultProtocol,
                               String defaultTransferType,
                               Monitor monitor) {
        this.mapper = typeManager.getMapper();
        this.managementBaseUrl = managementBaseUrl;
        this.localParticipantId = localParticipantId;
        this.defaultConnectorId = defaultConnectorId;
        this.defaultCounterPartyAddress = defaultCounterPartyAddress;
        this.defaultProtocol = defaultProtocol;
        this.defaultTransferType = defaultTransferType;
        this.monitor = monitor;
    }

    @POST
    public Response infer(String requestBody) {
        try {
            var requestNode = mapper.readTree(requestBody);
            if (requestNode == null || requestNode.isNull()) {
                return Response.status(Response.Status.BAD_REQUEST)
                        .entity("{\"error\":\"Missing request body\"}")
                        .build();
            }

            var method = firstNonBlank(textValue(requestNode, "method"), "POST").toUpperCase(Locale.ROOT);
            var path = firstNonBlank(textValue(requestNode, "path"), "");
            var payload = firstNode(requestNode, "payload", "body", "input");
            var headersNode = firstNode(requestNode, "headers");

            var edrInfo = resolveEdr(requestNode);
            if (edrInfo == null) {
                var assetId = textValue(requestNode, "assetId", "id");
                var contractId = textValue(requestNode, "contractId", "contractAgreementId", "agreementId");
                var transferId = textValue(requestNode, "transferProcessId", "transferId");
                if (assetId != null && !assetId.isBlank() && contractId == null && transferId == null) {
                    return Response.status(Response.Status.BAD_REQUEST)
                            .entity("{\"error\":\"No contract agreement found for assetId\"}")
                            .build();
                }
                return Response.status(Response.Status.BAD_REQUEST)
                        .entity("{\"error\":\"Missing assetId/transferProcessId/contractId or endpoint/authorization\"}")
                        .build();
            }
            if (edrInfo.endpoint == null || edrInfo.endpoint.isBlank()) {
                return Response.status(Response.Status.BAD_REQUEST)
                        .entity("{\"error\":\"EDR is missing endpoint (asset is not an HTTP endpoint)\"}")
                        .build();
            }

            var targetUrl = joinUrl(edrInfo.endpoint, path);
            var builder = HttpRequest.newBuilder()
                    .uri(URI.create(targetUrl));

            if (headersNode != null && headersNode.isObject()) {
                headersNode.fields().forEachRemaining(entry ->
                        builder.header(entry.getKey(), entry.getValue().asText()));
            }

            if (edrInfo.authHeader != null && edrInfo.authorization != null) {
                builder.header(edrInfo.authHeader, edrInfo.authorization);
            }

            if (!hasHeader(headersNode, ACCEPT)) {
                builder.header(ACCEPT, MediaType.APPLICATION_JSON);
            }

            var bodyPublisher = buildBodyPublisher(payload);
            builder.method(method, bodyPublisher);

            var response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));

            var contentType = response.headers().firstValue(CONTENT_TYPE).orElse(MediaType.APPLICATION_JSON);
            return Response.status(response.statusCode())
                    .header(CONTENT_TYPE, contentType)
                    .entity(response.body())
                    .build();
        } catch (Exception e) {
            monitor.warning("Inference failed: " + e.getMessage());
            return Response.status(Response.Status.INTERNAL_SERVER_ERROR)
                    .entity("{\"error\":\"Inference failed\"}")
                    .build();
        }
    }

    private EdrInfo resolveEdr(JsonNode requestNode) throws Exception {
        var endpoint = firstNonBlank(textValue(requestNode, "endpoint", "edrEndpoint"), null);
        var authorization = firstNonBlank(textValue(requestNode, "authorization", "edrToken", "authCode"), null);
        var authHeader = firstNonBlank(textValue(requestNode, "authHeader", "authKey"), AUTHORIZATION);
        if (endpoint != null && authorization != null) {
            return new EdrInfo(endpoint, authorization, authHeader);
        }

        var transferProcessId = textValue(requestNode, "transferProcessId", "transferId");
        if (transferProcessId == null || transferProcessId.isBlank()) {
            var contractId = firstNonBlank(
                    textValue(requestNode, "contractId", "contractAgreementId", "agreementId"), null);
            if (contractId == null || contractId.isBlank()) {
                var assetId = firstNonBlank(textValue(requestNode, "assetId", "id"), null);
                if (assetId == null || assetId.isBlank()) {
                    return null;
                }

                // Local-owner shortcut:
                // if asset is local and has a direct HttpData baseUrl, execute directly and skip contract+transfer.
                var localAssetEndpoint = resolveLocalAssetEndpoint(assetId);
                if (localAssetEndpoint != null) {
                    return new EdrInfo(localAssetEndpoint, null, null);
                }

                var agreementId = findAgreementIdForAsset(assetId);
                if (agreementId == null) {
                    return null;
                }

                return startTransferAndResolve(agreementId,
                        textValue(requestNode, "connectorId", "providerId"),
                        textValue(requestNode, "counterPartyAddress", "protocolAddress"),
                        textValue(requestNode, "protocol"),
                        textValue(requestNode, "transferType"));
            }
            return startTransferAndResolve(contractId,
                    textValue(requestNode, "connectorId", "providerId"),
                    textValue(requestNode, "counterPartyAddress", "protocolAddress"),
                    textValue(requestNode, "protocol"),
                    textValue(requestNode, "transferType"));
        }

        return waitForEdr(transferProcessId);
    }

    private String resolveLocalAssetEndpoint(String assetId) throws Exception {
        if (assetId == null || assetId.isBlank()) {
            return null;
        }

        // First try direct GET by ID.
        var dataAddressNode = resolveDataAddressByAssetGet(assetId);
        if (dataAddressNode == null || dataAddressNode.isNull()) {
            return null;
        }

        var dataAddressType = firstNonBlank(textValue(dataAddressNode, "type", "@type"), null);
        var baseUrl = firstNonBlank(
                textValue(dataAddressNode, "baseUrl", "edc:baseUrl", "endpoint", "endpointUrl"), null);

        if (baseUrl == null || baseUrl.isBlank()) {
            return null;
        }

        if (dataAddressType != null && !dataAddressType.toLowerCase(Locale.ROOT).contains("http")) {
            monitor.debug("Local asset is not HttpData; fallback to transfer flow for asset: " + assetId);
            return null;
        }

        monitor.debug("Using local direct inference path for asset: " + assetId + " -> " + baseUrl);
        return baseUrl;
    }

    private JsonNode resolveDataAddressByAssetGet(String assetId) throws Exception {
        // Encode "/" as "%2F" so path-param lookup treats it as one ID segment.
        var encodedAssetId = URLEncoder.encode(assetId, StandardCharsets.UTF_8);
        var request = HttpRequest.newBuilder()
                .uri(URI.create(managementBaseUrl + "/v3/assets/" + encodedAssetId))
                .header(ACCEPT, MediaType.APPLICATION_JSON)
                .GET()
                .build();

        var response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() / 100 != 2) {
            return null;
        }

        var assetNode = mapper.readTree(response.body());
        return firstNode(assetNode, "dataAddress", "edc:dataAddress");
    }

    private EdrInfo startTransferAndResolve(String contractId,
                                            String connectorId,
                                            String counterPartyAddress,
                                            String protocol,
                                            String transferType) throws Exception {
        var transferParams = resolveTransferParams(contractId, connectorId, counterPartyAddress, protocol, transferType);
        var resolvedConnectorId = transferParams.connectorId();
        var resolvedCounterPartyAddress = transferParams.counterPartyAddress();
        var resolvedProtocol = transferParams.protocol();
        var resolvedTransferType = transferParams.transferType();

        if (resolvedCounterPartyAddress == null || resolvedCounterPartyAddress.isBlank()
                || resolvedConnectorId == null || resolvedConnectorId.isBlank()
                || resolvedProtocol == null || resolvedProtocol.isBlank()) {
            monitor.warning("Inference transfer routing is incomplete. connectorId=" + resolvedConnectorId
                    + ", counterPartyAddress=" + resolvedCounterPartyAddress + ", protocol=" + resolvedProtocol);
            return null;
        }

        var createdTransferId = startTransfer(contractId, resolvedConnectorId, resolvedCounterPartyAddress,
                resolvedProtocol, resolvedTransferType);
        if (createdTransferId == null || createdTransferId.isBlank()) {
            return null;
        }

        return waitForEdr(createdTransferId);
    }

    private TransferParams resolveTransferParams(String contractId,
                                                 String connectorId,
                                                 String counterPartyAddress,
                                                 String protocol,
                                                 String transferType) throws Exception {
        var resolvedConnectorId = firstNonBlank(connectorId, null);
        var resolvedCounterPartyAddress = firstNonBlank(counterPartyAddress, null);
        var resolvedProtocol = firstNonBlank(protocol, null);
        var resolvedTransferType = firstNonBlank(transferType, defaultTransferType);

        JsonNode agreement = null;
        if (contractId != null && (!hasText(resolvedConnectorId) || !hasText(resolvedCounterPartyAddress))) {
            agreement = findAgreementById(contractId);
        }

        if (!hasText(resolvedConnectorId) && agreement != null) {
            resolvedConnectorId = inferRemoteParticipantId(agreement);
        }

        if ((!hasText(resolvedCounterPartyAddress) || !hasText(resolvedProtocol) || !hasText(resolvedConnectorId))
                && contractId != null) {
            var negotiation = findNegotiationByAgreementId(contractId);
            if (negotiation != null) {
                if (!hasText(resolvedCounterPartyAddress)) {
                    resolvedCounterPartyAddress = firstNonBlank(
                            textValue(negotiation, "counterPartyAddress", "protocolAddress",
                                    "edc:counterPartyAddress", "edc:protocolAddress"), null);
                }
                if (!hasText(resolvedProtocol)) {
                    resolvedProtocol = firstNonBlank(
                            textValue(negotiation, "protocol", "edc:protocol"), null);
                }
                if (!hasText(resolvedConnectorId)) {
                    resolvedConnectorId = firstNonBlank(
                            textValue(negotiation, "counterPartyId", "connectorId",
                                    "edc:counterPartyId", "edc:connectorId"), null);
                }
            }
        }

        if (!hasText(resolvedConnectorId)) {
            resolvedConnectorId = defaultConnectorId;
        }
        if (!hasText(resolvedCounterPartyAddress)) {
            resolvedCounterPartyAddress = defaultCounterPartyAddress;
        }
        if (!hasText(resolvedProtocol)) {
            resolvedProtocol = defaultProtocol;
        }

        return new TransferParams(resolvedConnectorId, resolvedCounterPartyAddress, resolvedProtocol, resolvedTransferType);
    }

    private EdrInfo waitForEdr(String transferProcessId) throws Exception {
        var edrUrl = managementBaseUrl + "/v3/edrs/" + transferProcessId + "/dataaddress";
        int attempts = 10;
        long delayMs = 500;

        for (int i = 0; i < attempts; i++) {
            var request = HttpRequest.newBuilder()
                    .uri(URI.create(edrUrl))
                    .header(ACCEPT, MediaType.APPLICATION_JSON)
                    .GET()
                    .build();

            var response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 == 2) {
                var edrNode = mapper.readTree(response.body());
                var resolvedEndpoint = firstNonBlank(
                        textValue(edrNode, "endpoint", "edc:endpoint", "edc:endpointUrl", "endpointUrl"), null);
                var resolvedAuth = firstNonBlank(
                        textValue(edrNode, "authorization", "edc:authorization", "authCode", "edc:authCode"), null);
                var resolvedAuthHeader = firstNonBlank(
                        textValue(edrNode, "authHeader", "authKey", "edc:authKey"), AUTHORIZATION);

                if (resolvedEndpoint != null && resolvedAuth != null) {
                    return new EdrInfo(resolvedEndpoint, resolvedAuth, resolvedAuthHeader);
                }
            } else {
                monitor.debug("EDR not ready yet: " + response.body());
            }

            Thread.sleep(delayMs);
        }

        monitor.warning("EDR lookup timed out for transfer process: " + transferProcessId);
        return null;
    }

    private String startTransfer(String contractId, String connectorId, String counterPartyAddress, String protocol, String transferType) throws Exception {
        var payload = mapper.createObjectNode();
        var contextNode = mapper.createObjectNode();
        contextNode.put("@vocab", "https://w3id.org/edc/v0.0.1/ns/");
        payload.set("@context", contextNode);
        payload.put("@type", "TransferRequestDto");
        payload.put("connectorId", connectorId);
        payload.put("counterPartyAddress", counterPartyAddress);
        payload.put("contractId", contractId);
        payload.put("protocol", protocol);
        payload.put("transferType", transferType);

        var request = HttpRequest.newBuilder()
                .uri(URI.create(managementBaseUrl + "/v3/transferprocesses"))
                .header(CONTENT_TYPE, MediaType.APPLICATION_JSON)
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(payload)))
                .build();

        var response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() / 100 != 2) {
            monitor.warning("Transfer request failed: " + response.body());
            return null;
        }

        var node = mapper.readTree(response.body());
        var transferId = firstNonBlank(textValue(node, "@id", "id"), null);
        if (transferId == null || transferId.isBlank()) {
            monitor.warning("Transfer request did not return an ID");
            return null;
        }
        return transferId;
    }

    private String findAgreementIdForAsset(String assetId) throws Exception {
        var agreements = listContractAgreements();
        if (agreements.isEmpty()) {
            return null;
        }

        String bestId = null;
        long bestTimestamp = Long.MIN_VALUE;

        for (JsonNode agreement : agreements) {
            var agreementAssetId = extractAssetId(agreement);
            if (agreementAssetId == null || !agreementAssetId.equals(assetId)) {
                continue;
            }

            var agreementId = firstNonBlank(
                    textValue(agreement, "@id", "id", "agreementId", "contractAgreementId"), null);
            if (agreementId == null) {
                continue;
            }

            var timestamp = extractTimestamp(agreement);
            if (timestamp > bestTimestamp) {
                bestTimestamp = timestamp;
                bestId = agreementId;
            } else if (bestId == null && timestamp == Long.MIN_VALUE) {
                bestId = agreementId;
            }
        }

        return bestId;
    }

    private JsonNode findAgreementById(String agreementId) throws Exception {
        if (!hasText(agreementId)) {
            return null;
        }

        for (var agreement : listContractAgreements()) {
            var id = firstNonBlank(
                    textValue(agreement, "@id", "id", "agreementId", "contractAgreementId"), null);
            if (hasText(id) && agreementId.equals(id)) {
                return agreement;
            }
        }
        return null;
    }

    private List<JsonNode> listContractAgreements() throws Exception {
        var requestBody = mapper.createObjectNode();
        var contextNode = mapper.createObjectNode();
        contextNode.put("@vocab", "https://w3id.org/edc/v0.0.1/ns/");
        requestBody.set("@context", contextNode);
        var querySpec = mapper.createObjectNode();
        querySpec.put("limit", 50);
        querySpec.set("filterExpression", mapper.createArrayNode());
        requestBody.set("querySpec", querySpec);

        var request = HttpRequest.newBuilder()
                .uri(URI.create(managementBaseUrl + "/v3/contractagreements/request"))
                .header(CONTENT_TYPE, MediaType.APPLICATION_JSON)
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(requestBody)))
                .build();

        var response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() / 100 != 2) {
            monitor.warning("Contract agreement query failed: " + response.body());
            return List.of();
        }

        var body = mapper.readTree(response.body());
        return extractAgreements(body);
    }

    private JsonNode findNegotiationByAgreementId(String agreementId) throws Exception {
        if (!hasText(agreementId)) {
            return null;
        }

        var requestBody = mapper.createObjectNode();
        var contextNode = mapper.createObjectNode();
        contextNode.put("@vocab", "https://w3id.org/edc/v0.0.1/ns/");
        requestBody.set("@context", contextNode);
        var querySpec = mapper.createObjectNode();
        querySpec.put("limit", 100);
        querySpec.set("filterExpression", mapper.createArrayNode());
        requestBody.set("querySpec", querySpec);

        var request = HttpRequest.newBuilder()
                .uri(URI.create(managementBaseUrl + "/v3/contractnegotiations/request"))
                .header(CONTENT_TYPE, MediaType.APPLICATION_JSON)
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(requestBody)))
                .build();

        var response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() / 100 != 2) {
            monitor.debug("Contract negotiation query failed: " + response.body());
            return null;
        }

        var body = mapper.readTree(response.body());
        var negotiations = extractAgreements(body);
        if (negotiations.isEmpty()) {
            return null;
        }

        JsonNode best = null;
        long bestTimestamp = Long.MIN_VALUE;

        for (JsonNode negotiation : negotiations) {
            var linkedAgreementId = firstNonBlank(
                    textValue(negotiation, "contractAgreementId", "agreementId", "edc:contractAgreementId",
                            "edc:agreementId"), null);
            if (linkedAgreementId == null || !linkedAgreementId.equals(agreementId)) {
                continue;
            }

            var state = firstNonBlank(
                    textValue(negotiation, "state", "edc:state", "negotiationState", "edc:negotiationState"), "");
            if (!"FINALIZED".equalsIgnoreCase(state)) {
                continue;
            }

            var timestamp = extractTimestamp(negotiation);
            if (timestamp > bestTimestamp) {
                bestTimestamp = timestamp;
                best = negotiation;
            } else if (best == null && timestamp == Long.MIN_VALUE) {
                best = negotiation;
            }
        }

        return best;
    }

    private List<JsonNode> extractAgreements(JsonNode body) {
        var result = new ArrayList<JsonNode>();
        if (body == null || body.isNull()) {
            return result;
        }
        if (body.isArray()) {
            body.forEach(result::add);
            return result;
        }
        var resultsNode = firstNode(body, "results", "items", "contractAgreements", "@graph");
        if (resultsNode != null && resultsNode.isArray()) {
            resultsNode.forEach(result::add);
        } else if (body.isObject()) {
            result.add(body);
        }
        return result;
    }

    private String extractAssetId(JsonNode agreement) {
        var assetId = firstNonBlank(
                textValue(agreement, "assetId", "edc:assetId", "https://w3id.org/edc/v0.0.1/ns/assetId"), null);
        if (assetId != null) {
            return assetId;
        }

        var assetNode = firstNode(agreement, "asset", "edc:asset");
        if (assetNode == null) {
            return null;
        }
        if (assetNode.isTextual()) {
            return assetNode.asText();
        }
        if (assetNode.isObject()) {
            return firstNonBlank(
                    textValue(assetNode, "@id", "id", "assetId"), null);
        }
        return null;
    }

    private long extractTimestamp(JsonNode agreement) {
        var raw = firstNonBlank(
                textValue(agreement, "contractSigningDate", "createdAt", "timestamp", "edc:contractSigningDate",
                        "edc:createdAt", "edc:timestamp"), null);
        if (raw == null) {
            return Long.MIN_VALUE;
        }
        try {
            return Long.parseLong(raw);
        } catch (NumberFormatException ignored) {
            try {
                return java.time.Instant.parse(raw).toEpochMilli();
            } catch (Exception ignoredAgain) {
                return Long.MIN_VALUE;
            }
        }
    }

    private HttpRequest.BodyPublisher buildBodyPublisher(JsonNode payload) throws Exception {
        if (payload == null || payload.isNull()) {
            return HttpRequest.BodyPublishers.noBody();
        }
        if (payload.isTextual()) {
            return HttpRequest.BodyPublishers.ofString(payload.asText(), StandardCharsets.UTF_8);
        }
        return HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(payload), StandardCharsets.UTF_8);
    }

    private JsonNode firstNode(JsonNode node, String... keys) {
        if (node == null || keys == null) {
            return null;
        }
        for (String key : keys) {
            if (node.has(key)) {
                return node.get(key);
            }
        }
        return null;
    }

    private boolean hasHeader(JsonNode headersNode, String headerName) {
        if (headersNode == null || !headersNode.isObject() || headerName == null) {
            return false;
        }
        var target = headerName.toLowerCase(Locale.ROOT);
        var fields = headersNode.fields();
        while (fields.hasNext()) {
            var entry = fields.next();
            if (entry.getKey().toLowerCase(Locale.ROOT).equals(target)) {
                return true;
            }
        }
        return false;
    }

    private String textValue(JsonNode node, String... keys) {
        var valueNode = firstNode(node, keys);
        if (valueNode == null || valueNode.isNull()) {
            return null;
        }
        if (valueNode.isTextual()) {
            return valueNode.asText();
        }
        return valueNode.toString();
    }

    private String firstNonBlank(String first, String fallback) {
        if (first != null && !first.isBlank()) {
            return first;
        }
        return fallback;
    }

    private String firstNonBlank(String first, String second, String third) {
        if (first != null && !first.isBlank()) {
            return first;
        }
        if (second != null && !second.isBlank()) {
            return second;
        }
        if (third != null && !third.isBlank()) {
            return third;
        }
        return null;
    }

    private String joinUrl(String base, String path) {
        if (base == null) {
            return null;
        }
        var trimmedBase = base.endsWith("/") ? base.substring(0, base.length() - 1) : base;
        var trimmedPath = path == null ? "" : path.trim();
        if (trimmedPath.isEmpty() || "/".equals(trimmedPath)) {
            return trimmedBase;
        }
        var normalizedPath = trimmedPath.startsWith("/") ? trimmedPath : "/" + trimmedPath;
        return trimmedBase + normalizedPath;
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private String inferRemoteParticipantId(JsonNode agreement) {
        if (agreement == null || agreement.isNull()) {
            return null;
        }

        var providerId = firstNonBlank(textValue(agreement, "providerId", "edc:providerId"), null);
        var consumerId = firstNonBlank(textValue(agreement, "consumerId", "edc:consumerId"), null);

        if (!hasText(localParticipantId)) {
            return firstNonBlank(providerId, consumerId, null);
        }
        if (localParticipantId.equals(providerId)) {
            return consumerId;
        }
        if (localParticipantId.equals(consumerId)) {
            return providerId;
        }
        return firstNonBlank(providerId, consumerId, null);
    }

    private record EdrInfo(String endpoint, String authorization, String authHeader) {
    }

    private record TransferParams(String connectorId, String counterPartyAddress, String protocol,
                                  String transferType) {
    }
}
