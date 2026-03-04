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

package com.pionera.assetfilter.contracts;

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

@Path("/contract-sequences")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
public class ContractSequenceController {
    private final ObjectMapper mapper;
    private final ContractSequenceStore store;
    private final Monitor monitor;

    public ContractSequenceController(TypeManager typeManager, ContractSequenceStore store, Monitor monitor) {
        this.mapper = typeManager.getMapper();
        this.store = store;
        this.monitor = monitor;
    }

    @POST
    @Path("/next")
    public Response next(String requestBody) {
        try {
            var userId = extractUserId(requestBody);
            var index = store.allocateNext(userId);
            var contractDefinitionId = userId + "~" + index;

            var response = mapper.createObjectNode();
            response.put("userId", userId);
            response.put("index", index);
            response.put("contractDefinitionId", contractDefinitionId);
            return Response.ok(mapper.writeValueAsString(response)).build();
        } catch (Exception e) {
            monitor.warning("Failed to allocate next contract ID: " + e.getMessage());
            return Response.status(Response.Status.INTERNAL_SERVER_ERROR)
                    .entity("{\"error\":\"Failed to allocate next contract ID\"}")
                    .build();
        }
    }

    @POST
    @Path("/peek")
    public Response peek(String requestBody) {
        try {
            var userId = extractUserId(requestBody);
            var index = store.peekNext(userId);
            var contractDefinitionId = userId + "~" + index;

            var response = mapper.createObjectNode();
            response.put("userId", userId);
            response.put("index", index);
            response.put("contractDefinitionId", contractDefinitionId);
            return Response.ok(mapper.writeValueAsString(response)).build();
        } catch (Exception e) {
            monitor.warning("Failed to peek next contract ID: " + e.getMessage());
            return Response.status(Response.Status.INTERNAL_SERVER_ERROR)
                    .entity("{\"error\":\"Failed to peek next contract ID\"}")
                    .build();
        }
    }

    @POST
    @Path("/commit")
    public Response commit(String requestBody) {
        try {
            var payload = parseRequestPayload(requestBody);
            var userId = payload.userId();
            var index = payload.index();
            if (index <= 0) {
                return Response.status(Response.Status.BAD_REQUEST)
                        .entity("{\"error\":\"index must be greater than zero\"}")
                        .build();
            }

            store.commitAtLeast(userId, index);

            var response = mapper.createObjectNode();
            response.put("userId", userId);
            response.put("committedIndex", index);
            return Response.ok(mapper.writeValueAsString(response)).build();
        } catch (Exception e) {
            monitor.warning("Failed to commit contract ID index: " + e.getMessage());
            return Response.status(Response.Status.INTERNAL_SERVER_ERROR)
                    .entity("{\"error\":\"Failed to commit contract ID index\"}")
                    .build();
        }
    }

    private String extractUserId(String requestBody) {
        return parseRequestPayload(requestBody).userId();
    }

    private SequencePayload parseRequestPayload(String requestBody) {
        try {
            if (requestBody == null || requestBody.isBlank()) {
                return new SequencePayload("user", 0L);
            }
            JsonNode root = mapper.readTree(requestBody);
            var userIdNode = root.get("userId");
            var indexNode = root.get("index");

            var userId = "user";
            if (userIdNode != null && !userIdNode.isNull()) {
                var value = userIdNode.asText();
                if (value != null && !value.isBlank()) {
                    userId = value.trim().toLowerCase();
                }
            }
            long index = 0L;
            if (indexNode != null && indexNode.canConvertToLong()) {
                index = indexNode.asLong();
            }

            return new SequencePayload(userId, index);
        } catch (Exception ignored) {
            return new SequencePayload("user", 0L);
        }
    }

    private record SequencePayload(String userId, long index) {
    }
}
