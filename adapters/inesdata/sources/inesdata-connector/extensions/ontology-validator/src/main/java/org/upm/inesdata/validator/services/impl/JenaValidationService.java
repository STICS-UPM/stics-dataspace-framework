package org.upm.inesdata.validator.services.impl;

import org.apache.jena.rdf.model.Model;
import org.apache.jena.rdf.model.ModelFactory;
import org.apache.jena.riot.Lang;
import org.apache.jena.riot.RDFDataMgr;
import org.apache.jena.shacl.ShaclValidator;
import org.apache.jena.shacl.Shapes;
import org.apache.jena.shacl.ValidationReport;
import org.apache.jena.reasoner.Reasoner;
import org.apache.jena.reasoner.ReasonerRegistry;
import org.apache.jena.rdf.model.InfModel;

import org.eclipse.edc.validator.spi.ValidationResult;
import org.eclipse.edc.validator.spi.Violation;
import org.upm.inesdata.validator.services.enums.RdfFormat;
import org.upm.inesdata.validator.services.RdfValidationService;

import java.io.InputStream;
import java.net.URL;
import java.util.List;

public class JenaValidationService implements RdfValidationService {

    @Override
    public ValidationResult validate(
            InputStream rdfStream,
            RdfFormat format,
            String ontologyUrl,
            String shaclUrl
    ) {
        // Transform URLs for minikube environment
        ontologyUrl = transformUrlForMinikube(ontologyUrl);
        shaclUrl = transformUrlForMinikube(shaclUrl);

        // 1. Load RDF data
        Model dataModel = ModelFactory.createDefaultModel();
        try {
            RDFDataMgr.read(dataModel, rdfStream, mapLang(format));
        } catch (Exception e) {
            return failure("RDF data parse error", "rdf", e);
        }

        // 2. Load ontology (required for validation with inference)
        Model ontologyModel = null;
        if (ontologyUrl != null && !ontologyUrl.isBlank()) {
            try {
                ontologyModel = loadOntologyModel(ontologyUrl);
            } catch (Exception e) {
                return failure("Ontology load error", ontologyUrl, e);
            }
        } else {
            return failure("Ontology URL is required", "", new IllegalArgumentException("ontologyUrl cannot be null or blank"));
        }

        // 3. Create inferred model using ontology
        Reasoner reasoner = ReasonerRegistry.getOWLReasoner();
        reasoner = reasoner.bindSchema(ontologyModel);
        InfModel infModel = ModelFactory.createInfModel(reasoner, dataModel);

        // 4. Load SHACL shapes
        Shapes shapes;
        try {
            Model shapesModel = RDFDataMgr.loadModel(shaclUrl);
            shapes = Shapes.parse(shapesModel);
        } catch (Exception e) {
            return failure("SHACL shapes load error", shaclUrl, e);
        }

        // 5. Validate
        final ValidationReport report;
        try {
            report = ShaclValidator.get().validate(shapes, infModel.getGraph());
        } catch (Exception e) {
            return failure("SHACL validation execution error", "", e);
        }

        if (report.conforms()) {
            return ValidationResult.success();
        }

        // 6. Map SHACL violations → EDC Violations
        List<Violation> violations = report.getEntries().stream()
                .map(e -> new Violation(
                        e.message(),
                        e.resultPath() != null ? e.resultPath().toString() : "",
                        e.value() != null ? e.value().toString() : ""
                ))
                .toList();

        return ValidationResult.failure(violations);
    }

    private ValidationResult failure(String message, String path, Exception e) {
        var detail = e.getMessage() != null ? e.getMessage() : e.toString();
        return ValidationResult.failure(List.of(new Violation(message, path != null ? path : "", detail)));
    }

    private Lang mapLang(RdfFormat format) {
        return switch (format) {
            case TURTLE -> Lang.TURTLE;
            case RDFXML -> Lang.RDFXML;
            case JSONLD -> Lang.JSONLD;
            case NTRIPLES -> Lang.NTRIPLES;
            case N3 -> Lang.N3;
        };
    }

    private Model loadOntologyModel(String ontologyUrl) {
        try {
            Model ontologyModel = RDFDataMgr.loadModel(ontologyUrl);
            return ontologyModel;
        } catch (Exception firstError) {
            // Fallback for ontology endpoints serving N3 with weak/incorrect content-type metadata.
            try (InputStream ontologyStream = new URL(ontologyUrl).openStream()) {
                Model ontologyModel = ModelFactory.createDefaultModel();
                RDFDataMgr.read(ontologyModel, ontologyStream, Lang.N3);
                return ontologyModel;
            } catch (Exception fallbackError) {
                firstError.addSuppressed(fallbackError);
                throw firstError;
            }
        }
    }

    private String transformUrlForMinikube(String url) {
        if (url != null) {
            return url.replace("ontology-hub-demo.dev.ds.dataspaceunit.upm", "demo-ontology-hub.components:3333");
        }
        return url;
    }
}