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

package com.pionera.assetfilter.observability;

import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.edc.spi.types.TypeManager;

@Path("/check")
@Produces(MediaType.APPLICATION_JSON)
public class ObservabilityController {

    private final TypeManager typeManager;

    public ObservabilityController(TypeManager typeManager) {
        this.typeManager = typeManager;
    }

    @GET
    @Path("/health")
    public Response health() {
        return Response.ok(status("health")).build();
    }

    @GET
    @Path("/liveness")
    public Response liveness() {
        return Response.ok(status("liveness")).build();
    }

    @GET
    @Path("/readiness")
    public Response readiness() {
        return Response.ok(status("readiness")).build();
    }

    @GET
    @Path("/startup")
    public Response startup() {
        return Response.ok(status("startup")).build();
    }

    private ObjectNode status(String component) {
        var mapper = typeManager.getMapper();
        var root = mapper.createObjectNode();
        var results = mapper.createArrayNode();
        results.add(componentResult(component));
        root.set("componentResults", results);
        root.put("isSystemHealthy", true);
        return root;
    }

    private ObjectNode componentResult(String component) {
        var node = typeManager.getMapper().createObjectNode();
        node.put("component", component);
        node.put("isHealthy", true);
        return node;
    }
}
