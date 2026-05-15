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

package com.pionera.assetfilter.proxy;

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DELETE;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.OPTIONS;
import jakarta.ws.rs.PATCH;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.container.ContainerRequestContext;
import jakarta.ws.rs.core.Context;
import jakarta.ws.rs.core.Response;
import org.eclipse.edc.connector.dataplane.spi.iam.DataPlaneAuthorizationService;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import static jakarta.ws.rs.core.HttpHeaders.ACCEPT;
import static jakarta.ws.rs.core.HttpHeaders.AUTHORIZATION;
import static jakarta.ws.rs.core.HttpHeaders.CONTENT_TYPE;
import static jakarta.ws.rs.core.MediaType.APPLICATION_OCTET_STREAM;
import static jakarta.ws.rs.core.MediaType.WILDCARD;
import static jakarta.ws.rs.core.Response.Status.FORBIDDEN;
import static jakarta.ws.rs.core.Response.Status.UNAUTHORIZED;
import static java.util.Collections.emptyMap;
import static org.eclipse.edc.spi.constants.CoreConstants.EDC_NAMESPACE;

@Path("{any:.*}")
@Consumes(WILDCARD)
@Produces(WILDCARD)
public class ProxyController {

    private final DataPlaneAuthorizationService authorizationService;
    private final HttpClient httpClient = HttpClient.newHttpClient();

    public ProxyController(DataPlaneAuthorizationService authorizationService) {
        this.authorizationService = authorizationService;
    }

    @GET
    public Response proxyGet(@Context ContainerRequestContext requestContext) {
        return proxyRequest(requestContext);
    }

    @POST
    public Response proxyPost(@Context ContainerRequestContext requestContext) {
        return proxyRequest(requestContext);
    }

    @PUT
    public Response proxyPut(@Context ContainerRequestContext requestContext) {
        return proxyRequest(requestContext);
    }

    @DELETE
    public Response proxyDelete(@Context ContainerRequestContext requestContext) {
        return proxyRequest(requestContext);
    }

    @PATCH
    public Response proxyPatch(@Context ContainerRequestContext requestContext) {
        return proxyRequest(requestContext);
    }

    @OPTIONS
    public Response proxyOptions(@Context ContainerRequestContext requestContext) {
        return proxyRequest(requestContext);
    }

    private Response proxyRequest(ContainerRequestContext requestContext) {
        var token = requestContext.getHeaderString(AUTHORIZATION);
        if (token == null) {
            return Response.status(UNAUTHORIZED).build();
        }

        var authorization = authorizationService.authorize(token, emptyMap());
        if (authorization.failed()) {
            return Response.status(FORBIDDEN).build();
        }

        var sourceDataAddress = authorization.getContent();

        try {
            var path = requestContext.getUriInfo().getPath();
            var query = requestContext.getUriInfo().getRequestUri().getRawQuery();
            var baseUrl = sourceDataAddress.getStringProperty(EDC_NAMESPACE + "baseUrl");
            var targetUrl = joinUrl(baseUrl, path);
            if (query != null && !query.isBlank()) {
                targetUrl = targetUrl + "?" + query;
            }

            var bodyBytes = requestContext.getEntityStream().readAllBytes();
            var bodyPublisher = bodyBytes.length > 0
                    ? HttpRequest.BodyPublishers.ofByteArray(bodyBytes)
                    : HttpRequest.BodyPublishers.noBody();

            var builder = HttpRequest.newBuilder()
                    .uri(URI.create(targetUrl))
                    .method(requestContext.getMethod(), bodyPublisher);

            var contentType = requestContext.getHeaderString(CONTENT_TYPE);
            if (contentType != null) {
                builder.header(CONTENT_TYPE, contentType);
            }

            var accept = requestContext.getHeaderString(ACCEPT);
            if (accept != null) {
                builder.header(ACCEPT, accept);
            }

            var response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofInputStream());
            return Response.status(response.statusCode())
                    .header(CONTENT_TYPE, response.headers().firstValue(CONTENT_TYPE).orElse(APPLICATION_OCTET_STREAM))
                    .entity(response.body())
                    .build();
        } catch (IOException | InterruptedException e) {
            return Response.status(Response.Status.BAD_GATEWAY)
                    .entity("{\"error\": \"Failed to contact backend service\"}")
                    .build();
        }
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
}
