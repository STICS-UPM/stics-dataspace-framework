package org.upm.inesdata.validator.controller;

import jakarta.ws.rs.*;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.validator.spi.ValidationResult;
import org.upm.inesdata.validator.dto.RdfValidationRequest;
import org.upm.inesdata.validator.dto.RdfValidationResponse;
import org.upm.inesdata.validator.services.enums.RdfFormat;
import org.upm.inesdata.validator.services.RdfValidationService;

import java.io.InputStream;

/**
 * REST endpoint for RDF validation callback.
 *
 * The consumer calls this endpoint after receiving RDF data
 * to validate it against ontology and SHACL shapes.
 *
 * Usage:
 *   POST /public/validation/rdf
 *   Content-Type: application/json
 *   {
 *     "transferId": "...",
 *     "rdfContent": "base64-encoded RDF data",
 *     "format": "TURTLE",
 *     "ontologyUrl": "http://...",
 *     "shaclUrl": "http://..."
 *   }
 */
@Path("public")
public class RdfValidationCallbackController {

    private final RdfValidationService validationService;
    private final Monitor monitor;

    public RdfValidationCallbackController(
            RdfValidationService validationService,
            Monitor monitor
    ) {
        this.validationService = validationService;
        this.monitor = monitor;
    }

    @POST
    @Path("validation/rdf")
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Response validateRdf(RdfValidationRequest request) {

        String transferId = request.getTransferId() != null ?
                request.getTransferId() : "unknown";

        monitor.info("📋 RDF Validation request received for transfer: " + transferId);

        try {
            // Validate input
            if (request.getRdfContent() == null || request.getRdfContent().isEmpty()) {
                return Response.status(400)
                        .entity(new RdfValidationResponse(
                                transferId,
                                false,
                                "RDF content is required"
                        ))
                        .build();
            }

            // Decode base64 RDF content
            byte[] decodedBytes = java.util.Base64.getDecoder()
                    .decode(request.getRdfContent());
            InputStream rdfStream = new java.io.ByteArrayInputStream(decodedBytes);

            // Parse format
            RdfFormat format = RdfFormat.fromInput(request.getFormat());

            // Resolve URLs (use defaults if not provided)
            String ontologyUrl = request.getOntologyUrl() != null ?
                    request.getOntologyUrl() :
                    "http://ontology-hub:3333/ontologies/default.n3";

            String shaclUrl = request.getShaclUrl() != null ?
                    request.getShaclUrl() :
                    "http://ontology-hub:3333/shacl/default.ttl";

            // Execute validation
            ValidationResult result = validationService.validate(
                    rdfStream,
                    format,
                    ontologyUrl,
                    shaclUrl
            );

            if (result.failed()) {
                monitor.warning(
                        "❌ RDF validation FAILED for transfer " + transferId
                );

                String failureMessage = result.toResult()
                        .getFailureMessages() != null ?
                        String.join("; ", result.toResult().getFailureMessages()) :
                        "Validation failed";

                return Response.ok(new RdfValidationResponse(
                        transferId,
                        false,
                        failureMessage
                )).build();
            }

            monitor.info(
                    "✅ RDF validation OK for transfer " + transferId
            );

            return Response.ok(new RdfValidationResponse(
                    transferId,
                    true,
                    "Validation passed"
            )).build();

        } catch (IllegalArgumentException e) {
            monitor.warning(
                    "⚠️ Invalid RDF format for transfer " + transferId + ": " + e.getMessage()
            );
            return Response.status(400)
                    .entity(new RdfValidationResponse(
                            transferId,
                            false,
                            "Invalid format: " + e.getMessage()
                    ))
                    .build();

        } catch (Exception e) {
            monitor.severe(
                    "💥 Error during RDF validation for transfer " + transferId,
                    e
            );
            return Response.status(500)
                    .entity(new RdfValidationResponse(
                            transferId,
                            false,
                            "Validation error: " + e.getMessage()
                    ))
                    .build();
        }
    }
}
