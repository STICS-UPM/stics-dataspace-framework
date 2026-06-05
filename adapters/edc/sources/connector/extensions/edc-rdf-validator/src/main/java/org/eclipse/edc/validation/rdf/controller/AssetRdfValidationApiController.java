package org.eclipse.edc.validation.rdf.controller;

import jakarta.ws.rs.*;
import jakarta.ws.rs.core.*;

import org.eclipse.edc.validator.spi.ValidationResult;
import org.glassfish.jersey.media.multipart.FormDataParam;
import org.eclipse.edc.validation.rdf.services.enums.RdfFormat;
import org.eclipse.edc.validation.rdf.services.RdfValidationService;

import java.io.InputStream;

@Path("/validation")
public class AssetRdfValidationApiController {

    private final RdfValidationService validationService;

    public AssetRdfValidationApiController(RdfValidationService validationService) {
        this.validationService = validationService;
    }

    @POST
    @Path("/rdf_asset")
    @Consumes(MediaType.MULTIPART_FORM_DATA)
    @Produces(MediaType.APPLICATION_JSON)
    public Response assetRdfValidation(
            @FormDataParam("ontologyUrl") String ontologyUrl,
            @FormDataParam("shaclUrl") String shaclUrl,
            @FormDataParam("rdf") InputStream rdfStream,
            @FormDataParam("format") String format
    ) {
        final RdfFormat rdfFormat;
        try {
            rdfFormat = RdfFormat.fromInput(format);
        } catch (IllegalArgumentException e) {
            return Response.status(Response.Status.BAD_REQUEST)
                    .entity(e.getMessage())
                    .build();
        }

        var result = validationService.validate(
                rdfStream,
                rdfFormat,
                ontologyUrl,
                shaclUrl
        );

        if (result.failed()) {
            return Response.status(Response.Status.BAD_REQUEST)
                    .entity(result.toResult().getFailureMessages())
                    .build();
        }

        return Response.ok().build();
    }
}
