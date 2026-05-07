package org.upm.inesdata.modelexecution.controller;

import jakarta.ws.rs.container.ContainerRequestContext;
import jakarta.ws.rs.container.ContainerRequestFilter;
import jakarta.ws.rs.container.ContainerResponseContext;
import jakarta.ws.rs.container.ContainerResponseFilter;
import jakarta.ws.rs.container.PreMatching;
import jakarta.ws.rs.core.MultivaluedMap;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.Provider;

@Provider
@PreMatching
public class ModelExecutionCorsFilter implements ContainerRequestFilter, ContainerResponseFilter {
    private static final String ALLOW_METHODS = "POST, OPTIONS";
    private static final String DEFAULT_ALLOW_HEADERS = "authorization,content-type,accept,origin";
    private static final String EXPOSE_HEADERS = "Content-Type";

    @Override
    public void filter(ContainerRequestContext requestContext) {
        if (!isModelExecutionRequest(requestContext)) {
            return;
        }

        if ("OPTIONS".equalsIgnoreCase(requestContext.getMethod())) {
            var responseBuilder = Response.ok();
            addCorsHeaders(requestContext, responseBuilder);
            requestContext.abortWith(responseBuilder.build());
        }
    }

    @Override
    public void filter(ContainerRequestContext requestContext, ContainerResponseContext responseContext) {
        if (!isModelExecutionRequest(requestContext)) {
            return;
        }

        addCorsHeaders(requestContext, responseContext.getHeaders());
    }

    private boolean isModelExecutionRequest(ContainerRequestContext requestContext) {
        var path = requestContext.getUriInfo().getPath();
        return path != null && path.contains("v3/modelexecutions");
    }

    private void addCorsHeaders(ContainerRequestContext requestContext, Response.ResponseBuilder responseBuilder) {
        var origin = resolveOrigin(requestContext);
        if (origin == null) {
            return;
        }

        responseBuilder
                .header("Access-Control-Allow-Origin", origin)
                .header("Vary", "Origin")
                .header("Access-Control-Allow-Methods", ALLOW_METHODS)
                .header("Access-Control-Allow-Headers", resolveRequestedHeaders(requestContext))
                .header("Access-Control-Expose-Headers", EXPOSE_HEADERS)
                .header("Access-Control-Max-Age", "86400");
    }

    private void addCorsHeaders(ContainerRequestContext requestContext, MultivaluedMap<String, Object> headers) {
        var origin = resolveOrigin(requestContext);
        if (origin == null) {
            return;
        }

        headers.putSingle("Access-Control-Allow-Origin", origin);
        headers.putSingle("Vary", "Origin");
        headers.putSingle("Access-Control-Allow-Methods", ALLOW_METHODS);
        headers.putSingle("Access-Control-Allow-Headers", resolveRequestedHeaders(requestContext));
        headers.putSingle("Access-Control-Expose-Headers", EXPOSE_HEADERS);
        headers.putSingle("Access-Control-Max-Age", "86400");
    }

    private String resolveOrigin(ContainerRequestContext requestContext) {
        var origin = requestContext.getHeaderString("Origin");
        return origin == null || origin.isBlank() ? null : origin;
    }

    private String resolveRequestedHeaders(ContainerRequestContext requestContext) {
        var requestedHeaders = requestContext.getHeaderString("Access-Control-Request-Headers");
        return requestedHeaders == null || requestedHeaders.isBlank() ? DEFAULT_ALLOW_HEADERS : requestedHeaders;
    }
}