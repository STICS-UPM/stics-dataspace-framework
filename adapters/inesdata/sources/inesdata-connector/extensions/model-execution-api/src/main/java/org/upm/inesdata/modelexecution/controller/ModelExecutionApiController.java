package org.upm.inesdata.modelexecution.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.Context;
import jakarta.ws.rs.core.HttpHeaders;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.security.Vault;
import org.eclipse.edc.spi.types.TypeManager;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import static jakarta.ws.rs.core.HttpHeaders.ACCEPT;
import static jakarta.ws.rs.core.HttpHeaders.AUTHORIZATION;
import static jakarta.ws.rs.core.HttpHeaders.CONTENT_TYPE;

@Path("/v3/modelexecutions")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
public class ModelExecutionApiController {
    private static final String DEFAULT_CONTEXT = "https://w3id.org/edc/v0.0.1/ns/";
    private static final long DEFAULT_EXECUTION_TARGET_CACHE_TTL_MS = 15 * 60 * 1000;

    private final ObjectMapper mapper;
    private final Monitor monitor;
    private final Vault vault;
    private final String managementBaseUrl;
    private final String localParticipantId;
    private final String defaultConnectorId;
    private final String defaultCounterPartyAddress;
    private final String defaultProtocol;
    private final String defaultTransferType;
    private final int edrAttempts;
    private final long edrDelayMs;
    private final String edrEndpointMode;
    private final boolean observerEnabled;
    private final String observerTargetUrl;
    private final String observerSourceComponent;
    private final HttpClient httpClient;
    private final Map<String, CachedExecutionTarget> executionTargetCache;

    public ModelExecutionApiController(TypeManager typeManager,
                                       Monitor monitor,
                                       Vault vault,
                                       String managementBaseUrl,
                                       String localParticipantId,
                                       String defaultConnectorId,
                                       String defaultCounterPartyAddress,
                                       String defaultProtocol,
                                       String defaultTransferType,
                                       int edrAttempts,
                                       long edrDelayMs,
                                       String edrEndpointMode,
                                       boolean observerEnabled,
                                       String observerJournalBaseUrl,
                                       String observerJournalEventsPath,
                                       String observerSourceComponent) {
        this.mapper = typeManager.getMapper();
        this.monitor = monitor;
        this.vault = vault;
        this.managementBaseUrl = trimTrailingSlash(managementBaseUrl);
        this.localParticipantId = localParticipantId;
        this.defaultConnectorId = defaultConnectorId;
        this.defaultCounterPartyAddress = defaultCounterPartyAddress;
        this.defaultProtocol = defaultProtocol;
        this.defaultTransferType = defaultTransferType;
        this.edrAttempts = Math.max(1, edrAttempts);
        this.edrDelayMs = Math.max(100L, edrDelayMs);
        this.edrEndpointMode = firstNonBlank(edrEndpointMode, "public").toLowerCase(Locale.ROOT);
        this.observerEnabled = observerEnabled;
        this.observerTargetUrl = buildObserverTargetUrl(observerJournalBaseUrl, observerJournalEventsPath);
        this.observerSourceComponent = firstNonBlank(observerSourceComponent, "inesdata-connector:model-execution-api");
        this.httpClient = HttpClient.newBuilder()
                .followRedirects(HttpClient.Redirect.NORMAL)
                .version(HttpClient.Version.HTTP_1_1)
                .build();
        this.executionTargetCache = new ConcurrentHashMap<>();
    }

    @POST
    @Path("/execute")
    public Response execute(String requestBody, @Context HttpHeaders httpHeaders) {
        long startedAt = System.currentTimeMillis();
        String assetId = null;
        String correlationId = null;
        String benchmarkRunId = null;
        String modelName = null;
        ResolvedExecutionTarget resolution = null;

        try {
            var requestNode = mapper.readTree(requestBody);
            if (requestNode == null || requestNode.isNull()) {
                return error(Response.Status.BAD_REQUEST, "Missing request body");
            }

            assetId = firstNonBlank(textValue(requestNode, "assetId"), null);
            if (!hasText(assetId)) {
                return error(Response.Status.BAD_REQUEST, "Missing assetId");
            }

            correlationId = firstNonBlank(textValue(requestNode, "correlationId", "requestId"), null);
            benchmarkRunId = firstNonBlank(textValue(requestNode, "benchmarkRunId"), null);
            modelName = firstNonBlank(textValue(requestNode, "modelName", "name"), null);

            var payload = firstNode(requestNode, "payload", "body", "input");
            if (payload == null || payload.isNull()) {
                return error(Response.Status.BAD_REQUEST, "Missing payload");
            }

            var authHeaderValue = firstNonBlank(httpHeaders.getHeaderString(AUTHORIZATION), null);
            resolution = resolveExecutionTarget(requestNode, assetId, authHeaderValue, benchmarkRunId);
            if (resolution == null || !hasText(resolution.endpoint())) {
                return error(Response.Status.BAD_REQUEST, "Unable to resolve executable endpoint for assetId");
            }

            publishExecutionEvent(
                    "MODEL_EXECUTION_REQUESTED",
                    "REQUESTED",
                    assetId,
                    correlationId,
                    benchmarkRunId,
                    modelName,
                    resolution,
                    null,
                    null,
                    startedAt
            );

            var requestedMethod = firstNonBlank(textValue(requestNode, "method"), resolution.method());
            var requestedPath = firstNonBlank(textValue(requestNode, "path"), resolution.path());
            if ("edr-http".equals(resolution.endpointKind())) {
                requestedPath = firstNonBlank(resolution.path(), "");
            }
            var headersNode = firstNode(requestNode, "headers");
            var outboundResponse = invokeTarget(resolution, requestedMethod, requestedPath, headersNode, payload);
            if (isAuthorizationFailure(outboundResponse.statusCode())) {
                evictCachedExecutionTarget(benchmarkRunId, assetId, authHeaderValue);
            }

            var contentType = outboundResponse.headers().firstValue(CONTENT_TYPE).orElse(MediaType.APPLICATION_JSON);
            publishExecutionEvent(
                    "MODEL_EXECUTION_COMPLETED",
                    "COMPLETED",
                    assetId,
                    correlationId,
                    benchmarkRunId,
                    modelName,
                    resolution,
                    outboundResponse.statusCode(),
                    contentType,
                    startedAt
            );
            return Response.status(outboundResponse.statusCode())
                    .header(CONTENT_TYPE, contentType)
                    .entity(outboundResponse.body())
                    .build();
        } catch (ExecutionException exception) {
            publishExecutionEvent(
                    "MODEL_EXECUTION_FAILED",
                    "FAILED",
                    assetId,
                    correlationId,
                    benchmarkRunId,
                    modelName,
                    resolution,
                    null,
                    exception.getMessage(),
                    startedAt
            );
            monitor.warning("Model execution request rejected: " + exception.getMessage());
            return error(Response.Status.BAD_REQUEST, exception.getMessage());
        } catch (Exception exception) {
            publishExecutionEvent(
                    "MODEL_EXECUTION_FAILED",
                    "FAILED",
                    assetId,
                    correlationId,
                    benchmarkRunId,
                    modelName,
                    resolution,
                    null,
                    exception.getMessage(),
                    startedAt
            );
            monitor.severe("Model execution failed", exception);
            return error(Response.Status.INTERNAL_SERVER_ERROR, "Model execution failed");
        }
    }

    private HttpResponse<String> invokeTarget(ResolvedExecutionTarget resolution,
                                              String method,
                                              String path,
                                              JsonNode headersNode,
                                              JsonNode payload) throws Exception {
        var resolvedMethod = firstNonBlank(method, resolution.method(), "POST").toUpperCase(Locale.ROOT);
        var resolvedPath = firstNonBlank(path, resolution.path(), "");
        var requestBuilder = HttpRequest.newBuilder()
                .uri(URI.create(joinUrl(resolution.endpoint(), resolvedPath)));

        if (headersNode != null && headersNode.isObject()) {
            headersNode.fields().forEachRemaining(entry -> requestBuilder.header(entry.getKey(), entry.getValue().asText()));
        }

        if (hasText(resolution.authHeader()) && hasText(resolution.authValue()) && !hasHeader(headersNode, resolution.authHeader())) {
            requestBuilder.header(resolution.authHeader(), resolution.authValue());
        }

        if (!hasHeader(headersNode, ACCEPT)) {
            requestBuilder.header(ACCEPT, MediaType.APPLICATION_JSON);
        }

        if (!hasHeader(headersNode, CONTENT_TYPE)) {
            requestBuilder.header(CONTENT_TYPE, MediaType.APPLICATION_JSON);
        }

        requestBuilder.method(resolvedMethod, buildBodyPublisher(payload));
        return httpClient.send(requestBuilder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    private ResolvedExecutionTarget resolveExecutionTarget(JsonNode requestNode,
                                                           String assetId,
                                                           String managementAuthorization,
                                                           String benchmarkRunId) throws Exception {
        var cacheKey = executionTargetCacheKey(benchmarkRunId, assetId, managementAuthorization);
        var cachedTarget = cachedExecutionTarget(cacheKey);
        if (cachedTarget != null) {
            return cachedTarget;
        }

        var localTarget = resolveLocalAsset(assetId, managementAuthorization);
        if (localTarget != null) {
            return localTarget;
        }

        var agreementId = findAgreementIdForAsset(assetId, managementAuthorization);
        if (!hasText(agreementId)) {
            throw new ExecutionException("No finalized contract agreement found for assetId");
        }

        var transferParams = resolveTransferParams(
                agreementId,
                firstNonBlank(textValue(requestNode, "connectorId", "providerId"), null),
                firstNonBlank(textValue(requestNode, "counterPartyAddress", "protocolAddress"), null),
                firstNonBlank(textValue(requestNode, "protocol"), null),
                firstNonBlank(textValue(requestNode, "transferType"), null),
                managementAuthorization
        );

        var transferId = startTransfer(agreementId, transferParams, managementAuthorization);
        if (!hasText(transferId)) {
            throw new ExecutionException("Unable to initiate transfer for assetId");
        }

        var edrInfo = waitForEdr(transferId, managementAuthorization);
        if (edrInfo == null || !hasText(edrInfo.endpoint())) {
            throw new ExecutionException("Unable to resolve EDR for assetId");
        }

        var target = new ResolvedExecutionTarget(
            normalizeEdrEndpoint(edrInfo.endpoint(), transferParams.connectorId()),
            "POST",
            "",
            edrInfo.authHeader(),
            edrInfo.authorization(),
            agreementId,
            transferId,
            "federated-with-agreement",
            "edr-http",
            transferParams.connectorId()
        );
        cacheExecutionTarget(cacheKey, target);
        return target;
    }

    private ResolvedExecutionTarget cachedExecutionTarget(String cacheKey) {
        if (!hasText(cacheKey)) {
            return null;
        }

        var cachedTarget = executionTargetCache.get(cacheKey);
        if (cachedTarget == null) {
            return null;
        }

        if (cachedTarget.isFresh(System.currentTimeMillis())) {
            return cachedTarget.target();
        }

        executionTargetCache.remove(cacheKey, cachedTarget);
        return null;
    }

    private void cacheExecutionTarget(String cacheKey, ResolvedExecutionTarget target) {
        if (!hasText(cacheKey) || target == null || !"federated-with-agreement".equals(target.executionMode())) {
            return;
        }
        executionTargetCache.put(cacheKey, new CachedExecutionTarget(
                target,
                System.currentTimeMillis() + DEFAULT_EXECUTION_TARGET_CACHE_TTL_MS
        ));
    }

    private void evictCachedExecutionTarget(String benchmarkRunId, String assetId, String managementAuthorization) {
        var cacheKey = executionTargetCacheKey(benchmarkRunId, assetId, managementAuthorization);
        if (hasText(cacheKey)) {
            executionTargetCache.remove(cacheKey);
        }
    }

    private String executionTargetCacheKey(String benchmarkRunId, String assetId, String managementAuthorization) {
        if (!hasText(benchmarkRunId) || !hasText(assetId)) {
            return null;
        }
        return benchmarkRunId + "|" + assetId + "|" + authFingerprint(managementAuthorization);
    }

    private String authFingerprint(String managementAuthorization) {
        if (!hasText(managementAuthorization)) {
            return "anonymous";
        }
        try {
            var digest = MessageDigest.getInstance("SHA-256").digest(managementAuthorization.getBytes(StandardCharsets.UTF_8));
            return Base64.getUrlEncoder().withoutPadding().encodeToString(digest);
        } catch (NoSuchAlgorithmException exception) {
            return Integer.toHexString(managementAuthorization.hashCode());
        }
    }

    private boolean isAuthorizationFailure(int statusCode) {
        return statusCode == 401 || statusCode == 403;
    }

    private ResolvedExecutionTarget resolveLocalAsset(String assetId, String managementAuthorization) throws Exception {
        var assetNode = getJson("/v3/assets/" + encodePathSegment(assetId), managementAuthorization);
        if (assetNode == null || assetNode.isNull()) {
            return null;
        }

        var dataAddress = firstNode(assetNode, "dataAddress", "edc:dataAddress");
        if (dataAddress == null || dataAddress.isNull()) {
            return null;
        }

        var type = firstNonBlank(textValue(dataAddress, "type", "@type", "edc:type"), null);
        if (!hasText(type) || !type.toLowerCase(Locale.ROOT).contains("http")) {
            return null;
        }

        var endpoint = firstNonBlank(textValue(dataAddress, "baseUrl", "edc:baseUrl", "endpoint", "endpointUrl"), null);
        if (!hasText(endpoint)) {
            return null;
        }

        var path = firstNonBlank(textValue(dataAddress, "path", "edc:path", "proxyPath", "edc:proxyPath"), "");
        var method = firstNonBlank(textValue(dataAddress, "method", "edc:method"), "POST");
        var authValue = firstNonBlank(resolveAuthValue(dataAddress), null);
        var authHeader = firstNonBlank(textValue(dataAddress, "authKey", "edc:authKey"), hasText(authValue) ? AUTHORIZATION : null);

        return new ResolvedExecutionTarget(
                endpoint,
                method,
                path,
                authHeader,
                authValue,
                null,
                null,
                "local",
                "local-http",
                localParticipantId
        );
    }

    private void publishExecutionEvent(String eventType,
                                       String status,
                                       String assetId,
                                       String correlationId,
                                       String benchmarkRunId,
                                       String modelName,
                                       ResolvedExecutionTarget resolution,
                                       Integer httpStatus,
                                       String detailMessage,
                                       long startedAt) {
        if (!observerEnabled || !hasText(observerTargetUrl) || !hasText(assetId)) {
            return;
        }

        try {
            Map<String, Object> event = new LinkedHashMap<>();
            event.put("eventId", UUID.randomUUID().toString());
            event.put("eventType", eventType);
            event.put("occurredAt", Instant.now().toString());
            event.put("sourceComponent", observerSourceComponent);
            event.put("participantId", localParticipantId);
            event.put("assetId", assetId);
            event.put("status", status);
            event.put("latencyMs", System.currentTimeMillis() - startedAt);

            putIfHasText(event, "correlationId", correlationId);
            putIfHasText(event, "benchmarkRunId", benchmarkRunId);
            putIfHasText(event, "modelName", modelName);

            if (resolution != null) {
                putIfHasText(event, "agreementId", resolution.agreementId());
                putIfHasText(event, "transferProcessId", resolution.transferProcessId());
                putIfHasText(event, "executionMode", resolution.executionMode());
                putIfHasText(event, "endpointKind", resolution.endpointKind());
                putIfHasText(event, "providerParticipantId", resolution.remoteParticipantId());
                event.put("consumerParticipantId", localParticipantId);
            }

            if (httpStatus != null) {
                event.put("httpStatus", httpStatus);
            }

            Map<String, Object> details = new LinkedHashMap<>();
            if (resolution != null) {
                putIfHasText(details, "method", resolution.method());
                putIfHasText(details, "path", resolution.path());
            }
            putIfHasText(details, "message", detailMessage);
            if (!details.isEmpty()) {
                event.put("details", details);
            }

            var request = HttpRequest.newBuilder()
                    .uri(URI.create(observerTargetUrl))
                    .header(CONTENT_TYPE, MediaType.APPLICATION_JSON)
                    .header(ACCEPT, MediaType.APPLICATION_JSON)
                    .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(event), StandardCharsets.UTF_8))
                    .build();

            var response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                monitor.warning("Model execution observer journal publish failed with status " + response.statusCode() + ": " + response.body());
            }
        } catch (Exception exception) {
            monitor.warning("Model execution observer publish failed: " + exception.getMessage());
        }
    }

    private String resolveAuthValue(JsonNode dataAddress) {
        var directAuthCode = firstNonBlank(textValue(dataAddress, "authCode", "edc:authCode"), null);
        var secretName = firstNonBlank(textValue(dataAddress, "secretName", "edc:secretName"), null);
        if (hasText(secretName)) {
            var resolvedSecret = vault.resolveSecret(secretName);
            if (hasText(resolvedSecret)) {
                return resolvedSecret;
            }
        }
        return directAuthCode;
    }

    private String findAgreementIdForAsset(String assetId, String managementAuthorization) throws Exception {
        var agreements = listResults("/v3/contractagreements/request", managementAuthorization);
        String bestAgreementId = null;
        long bestTimestamp = Long.MIN_VALUE;

        for (var agreement : agreements) {
            var agreementAssetId = extractAgreementAssetId(agreement);
            if (!assetId.equals(agreementAssetId)) {
                continue;
            }

            var agreementId = firstNonBlank(textValue(agreement, "@id", "id", "contractAgreementId", "agreementId"), null);
            if (!hasText(agreementId)) {
                continue;
            }

            var timestamp = extractTimestamp(agreement);
            if (timestamp > bestTimestamp || bestAgreementId == null) {
                bestTimestamp = timestamp;
                bestAgreementId = agreementId;
            }
        }

        return bestAgreementId;
    }

    private TransferParams resolveTransferParams(String agreementId,
                                                 String connectorId,
                                                 String counterPartyAddress,
                                                 String protocol,
                                                 String transferType,
                                                 String managementAuthorization) throws Exception {
        var resolvedConnectorId = firstNonBlank(connectorId, defaultConnectorId);
        var resolvedCounterPartyAddress = firstNonBlank(counterPartyAddress, defaultCounterPartyAddress);
        var resolvedProtocol = firstNonBlank(protocol, defaultProtocol);
        var resolvedTransferType = firstNonBlank(transferType, defaultTransferType);

        var agreement = findAgreementById(agreementId, managementAuthorization);
        if (!hasText(resolvedConnectorId) && agreement != null) {
            resolvedConnectorId = inferRemoteParticipantId(agreement);
        }

        var negotiation = findNegotiationByAgreementId(agreementId, managementAuthorization);
        if (negotiation != null) {
            if (!hasText(resolvedCounterPartyAddress)) {
                resolvedCounterPartyAddress = firstNonBlank(textValue(negotiation,
                        "counterPartyAddress", "protocolAddress", "edc:counterPartyAddress", "edc:protocolAddress"), null);
            }
            if (!hasText(resolvedProtocol)) {
                resolvedProtocol = firstNonBlank(textValue(negotiation, "protocol", "edc:protocol"), null);
            }
            if (!hasText(resolvedConnectorId)) {
                resolvedConnectorId = firstNonBlank(textValue(negotiation,
                        "counterPartyId", "connectorId", "edc:counterPartyId", "edc:connectorId"), null);
            }
        }

        if (!hasText(resolvedConnectorId) || !hasText(resolvedCounterPartyAddress) || !hasText(resolvedProtocol)) {
            throw new ExecutionException("Missing transfer routing information for assetId");
        }

        return new TransferParams(resolvedConnectorId, resolvedCounterPartyAddress, resolvedProtocol, resolvedTransferType);
    }

    private String startTransfer(String agreementId,
                                 TransferParams transferParams,
                                 String managementAuthorization) throws Exception {
        var body = mapper.createObjectNode();
        body.put("@type", "TransferRequestDto");
        body.set("@context", defaultContextNode());
        body.put("connectorId", transferParams.connectorId());
        body.put("counterPartyAddress", transferParams.counterPartyAddress());
        body.put("contractId", agreementId);
        body.put("protocol", transferParams.protocol());
        body.put("transferType", transferParams.transferType());

        var response = postJson("/v3/transferprocesses", body, managementAuthorization);
        if (response == null) {
            return null;
        }

        return firstNonBlank(textValue(response, "@id", "id"), null);
    }

    private EdrInfo waitForEdr(String transferId, String managementAuthorization) throws Exception {
        for (int attempt = 0; attempt < edrAttempts; attempt++) {
            var edrNode = getJson("/v3/edrs/" + encodePathSegment(transferId) + "/dataaddress", managementAuthorization);
            if (edrNode != null && !edrNode.isNull()) {
                var endpoint = firstNonBlank(textValue(edrNode, "endpoint", "edc:endpoint", "endpointUrl", "edc:endpointUrl"), null);
                var authorization = firstNonBlank(textValue(edrNode, "authorization", "edc:authorization", "authCode", "edc:authCode"), null);
                var authHeader = firstNonBlank(textValue(edrNode, "authHeader", "edc:authHeader", "authKey", "edc:authKey"), AUTHORIZATION);
                if (hasText(endpoint) && hasText(authorization)) {
                    return new EdrInfo(endpoint, authorization, authHeader);
                }
            }
            Thread.sleep(edrDelayMs);
        }

        return null;
    }

    private JsonNode findAgreementById(String agreementId, String managementAuthorization) throws Exception {
        for (var agreement : listResults("/v3/contractagreements/request", managementAuthorization)) {
            var currentId = firstNonBlank(textValue(agreement, "@id", "id", "contractAgreementId", "agreementId"), null);
            if (agreementId.equals(currentId)) {
                return agreement;
            }
        }
        return null;
    }

    private JsonNode findNegotiationByAgreementId(String agreementId, String managementAuthorization) throws Exception {
        JsonNode selected = null;
        long bestTimestamp = Long.MIN_VALUE;

        for (var negotiation : listResults("/v3/contractnegotiations/request", managementAuthorization)) {
            var linkedAgreementId = firstNonBlank(textValue(negotiation,
                    "contractAgreementId", "agreementId", "edc:contractAgreementId", "edc:agreementId"), null);
            var state = firstNonBlank(textValue(negotiation, "state", "edc:state"), "");
            if (!agreementId.equals(linkedAgreementId) || !("FINALIZED".equalsIgnoreCase(state) || "VERIFIED".equalsIgnoreCase(state))) {
                continue;
            }

            var timestamp = extractTimestamp(negotiation);
            if (timestamp > bestTimestamp || selected == null) {
                bestTimestamp = timestamp;
                selected = negotiation;
            }
        }

        return selected;
    }

    private List<JsonNode> listResults(String path, String managementAuthorization) throws Exception {
        var query = mapper.createObjectNode();
        query.set("@context", defaultContextNode());
        query.put("offset", 0);
        query.put("limit", 1000);
        query.putArray("filterExpression");

        var response = postJson(path, query, managementAuthorization);
        var results = new ArrayList<JsonNode>();
        if (response == null || response.isNull()) {
            return results;
        }

        if (response.isArray()) {
            response.forEach(results::add);
            return results;
        }

        var nestedResults = firstNode(response, "results", "items", "contractAgreements", "@graph");
        if (nestedResults != null && nestedResults.isArray()) {
            nestedResults.forEach(results::add);
            return results;
        }

        results.add(response);
        return results;
    }

    private JsonNode getJson(String path, String managementAuthorization) throws Exception {
        var requestBuilder = HttpRequest.newBuilder()
                .uri(URI.create(managementBaseUrl + path))
                .header(ACCEPT, MediaType.APPLICATION_JSON)
                .GET();

        if (hasText(managementAuthorization)) {
            requestBuilder.header(AUTHORIZATION, managementAuthorization);
        }

        var response = httpClient.send(requestBuilder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() / 100 != 2) {
            return null;
        }
        return mapper.readTree(response.body());
    }

    private JsonNode postJson(String path, JsonNode body, String managementAuthorization) throws Exception {
        var requestBuilder = HttpRequest.newBuilder()
                .uri(URI.create(managementBaseUrl + path))
                .header(CONTENT_TYPE, MediaType.APPLICATION_JSON)
                .header(ACCEPT, MediaType.APPLICATION_JSON)
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)));

        if (hasText(managementAuthorization)) {
            requestBuilder.header(AUTHORIZATION, managementAuthorization);
        }

        var response = httpClient.send(requestBuilder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() / 100 != 2) {
            monitor.warning("Model execution management call failed for %s: %s".formatted(path, response.body()));
            return null;
        }
        return mapper.readTree(response.body());
    }

    private JsonNode defaultContextNode() {
        var context = mapper.createObjectNode();
        context.put("@vocab", DEFAULT_CONTEXT);
        return context;
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

    private String extractAgreementAssetId(JsonNode agreement) {
        var assetId = firstNonBlank(textValue(agreement, "assetId", "edc:assetId", "https://w3id.org/edc/v0.0.1/ns/assetId"), null);
        if (hasText(assetId)) {
            return assetId;
        }

        var assetNode = firstNode(agreement, "asset", "edc:asset");
        if (assetNode == null || assetNode.isNull()) {
            return null;
        }
        if (assetNode.isTextual()) {
            return assetNode.asText();
        }
        return firstNonBlank(textValue(assetNode, "@id", "id", "assetId"), null);
    }

    private long extractTimestamp(JsonNode node) {
        var rawValue = firstNonBlank(textValue(node, "contractSigningDate", "createdAt", "timestamp", "edc:createdAt", "edc:timestamp"), null);
        if (!hasText(rawValue)) {
            return Long.MIN_VALUE;
        }
        try {
            return Long.parseLong(rawValue);
        } catch (NumberFormatException ignored) {
            try {
                return java.time.Instant.parse(rawValue).toEpochMilli();
            } catch (Exception ignoredAgain) {
                return Long.MIN_VALUE;
            }
        }
    }

    private String inferRemoteParticipantId(JsonNode agreement) {
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

    private JsonNode firstNode(JsonNode node, String... keys) {
        if (node == null || keys == null) {
            return null;
        }
        for (var key : keys) {
            if (node.has(key)) {
                return node.get(key);
            }
        }
        return null;
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

    private boolean hasHeader(JsonNode headersNode, String headerName) {
        if (headersNode == null || !headersNode.isObject() || !hasText(headerName)) {
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

    private String joinUrl(String base, String path) {
        var normalizedBase = trimTrailingSlash(base);
        var normalizedPath = firstNonBlank(path, "");
        if (!hasText(normalizedPath) || "/".equals(normalizedPath)) {
            return normalizedBase;
        }
        return normalizedBase + (normalizedPath.startsWith("/") ? normalizedPath : "/" + normalizedPath);
    }

    private String normalizeEdrEndpoint(String endpoint, String remoteParticipantId) {
        if (!hasText(endpoint)) {
            return endpoint;
        }

        try {
            var uri = URI.create(endpoint);
            var host = firstNonBlank(uri.getHost(), "").toLowerCase(Locale.ROOT);
            var path = firstNonBlank(uri.getPath(), "");
            if (!host.endsWith(".pionera.oeg.fi.upm.es") || !"/public".equals(path)) {
                return endpoint;
            }

            if (shouldUsePublicHttpEdrEndpoint() && "https".equalsIgnoreCase(uri.getScheme())) {
                return "http://" + host
                        + (uri.getPort() > 0 && uri.getPort() != 443 ? ":" + uri.getPort() : "")
                        + path
                        + (hasText(uri.getQuery()) ? "?" + uri.getQuery() : "")
                        + (hasText(uri.getFragment()) ? "#" + uri.getFragment() : "");
            }

            if (!shouldUseInternalKubernetesEdrEndpoint() || !hasText(remoteParticipantId)) {
                return endpoint;
            }

            var namespace = inferPioneraConnectorNamespace(remoteParticipantId);
            if (!hasText(namespace)) {
                return endpoint;
            }

            var internalBase = "http://%s.%s.svc.cluster.local:19291".formatted(remoteParticipantId, namespace);
            return internalBase + path
                    + (hasText(uri.getQuery()) ? "?" + uri.getQuery() : "")
                    + (hasText(uri.getFragment()) ? "#" + uri.getFragment() : "");
        } catch (RuntimeException exception) {
            return endpoint;
        }
    }

    private boolean shouldUsePublicHttpEdrEndpoint() {
        return "public-http".equals(edrEndpointMode)
                || "http".equals(edrEndpointMode);
    }

    private boolean shouldUseInternalKubernetesEdrEndpoint() {
        return "internal-k8s".equals(edrEndpointMode)
                || "kubernetes".equals(edrEndpointMode)
                || "k8s".equals(edrEndpointMode);
    }

    private String inferPioneraConnectorNamespace(String participantId) {
        var value = firstNonBlank(participantId, "").toLowerCase(Locale.ROOT);
        if (value.contains("org2")) {
            return "provider";
        }
        if (value.contains("org3")) {
            return "consumer";
        }
        return "";
    }

    private String encodePathSegment(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    private String trimTrailingSlash(String value) {
        if (!hasText(value)) {
            return "";
        }
        return value.endsWith("/") ? value.substring(0, value.length() - 1) : value;
    }

    private String buildObserverTargetUrl(String journalBaseUrl, String journalEventsPath) {
        if (!hasText(journalBaseUrl)) {
            return "";
        }

        var normalizedBaseUrl = trimTrailingSlash(journalBaseUrl);
        var normalizedPath = firstNonBlank(journalEventsPath, "/api/model-observer/events");
        if (!normalizedPath.startsWith("/")) {
            normalizedPath = "/" + normalizedPath;
        }
        return normalizedBaseUrl + normalizedPath;
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private String firstNonBlank(String first, String fallback) {
        return hasText(first) ? first : fallback;
    }

    private String firstNonBlank(String first, String second, String third) {
        if (hasText(first)) {
            return first;
        }
        if (hasText(second)) {
            return second;
        }
        return third;
    }

    private void putIfHasText(Map<String, Object> target, String key, String value) {
        if (target != null && hasText(key) && hasText(value)) {
            target.put(key, value);
        }
    }

    private Response error(Response.Status status, String message) {
        var payload = mapper.createObjectNode();
        payload.put("error", message);
        return Response.status(status).entity(payload.toString()).build();
    }

    private record TransferParams(String connectorId, String counterPartyAddress, String protocol, String transferType) {
    }

    private record EdrInfo(String endpoint, String authorization, String authHeader) {
    }

    private record ResolvedExecutionTarget(String endpoint,
                                           String method,
                                           String path,
                                           String authHeader,
                                           String authValue,
                                           String agreementId,
                                           String transferProcessId,
                                           String executionMode,
                                           String endpointKind,
                                           String remoteParticipantId) {
    }

    private record CachedExecutionTarget(ResolvedExecutionTarget target, long expiresAtMillis) {
        private boolean isFresh(long nowMillis) {
            return target != null && expiresAtMillis > nowMillis;
        }
    }

    private static class ExecutionException extends RuntimeException {
        private ExecutionException(String message) {
            super(message);
        }
    }
}
