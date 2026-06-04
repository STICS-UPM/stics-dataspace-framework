package org.eclipse.edc.validation.rdf.services.impl;

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
import org.eclipse.edc.validation.rdf.services.enums.RdfFormat;
import org.eclipse.edc.validation.rdf.services.RdfValidationService;

import java.io.InputStream;
import java.net.URI;
import java.util.ArrayList;
import java.util.List;

public class JenaValidationService implements RdfValidationService {

    /** External Ontology Hub URL (browser / dashboard). */
    private static final String ONTOLOGY_HUB_EXTERNAL_BASE =
            getenvOrDefault("ONTOLOGY_HUB_EXTERNAL_BASE", "http://ontology-hub-demo.dev.ds.dataspaceunit.upm");
    /** In-cluster Ontology Hub service (release pionera-edc-ontology-hub @ components). */
    private static final String ONTOLOGY_HUB_INTERNAL_BASE =
            getenvOrDefault("ONTOLOGY_HUB_INTERNAL_BASE", "http://pionera-edc-ontology-hub.components:3333");
    /** Fallback internal host name when the release-specific service URL is unavailable. */
    private static final String ONTOLOGY_HUB_INTERNAL_FALLBACK =
            getenvOrDefault("ONTOLOGY_HUB_INTERNAL_FALLBACK", "http://ontology-hub:3333");
    /** Fully qualified internal host name for Kubernetes service discovery. */
    private static final String ONTOLOGY_HUB_INTERNAL_CLUSTERLOCAL_FALLBACK =
            getenvOrDefault("ONTOLOGY_HUB_INTERNAL_CLUSTERLOCAL_FALLBACK", "http://pionera-edc-ontology-hub.components.svc.cluster.local:3333");

    private static final List<String> ONTOLOGY_HUB_INTERNAL_CANDIDATES = List.of(
            ONTOLOGY_HUB_INTERNAL_BASE,
            ONTOLOGY_HUB_INTERNAL_CLUSTERLOCAL_FALLBACK,
            ONTOLOGY_HUB_INTERNAL_FALLBACK
    );

    private static String getenvOrDefault(String name, String defaultValue) {
        String value = System.getenv(name);
        return value != null && !value.isBlank() ? value.trim() : defaultValue;
    }

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
                ontologyModel = loadRemoteModel(ontologyUrl);
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
            Model shapesModel = loadRemoteModel(shaclUrl);
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

    private Model loadRemoteModel(String url) {
        List<String> candidates = createUrlCandidates(url);
        Exception lastError = null;

        for (String candidate : candidates) {
            try {
                return loadModel(candidate);
            } catch (Exception e) {
                lastError = e;
            }
        }

        if (lastError != null) {
            throw new IllegalStateException(
                    "Remote model load failed for candidates: " + candidates,
                    lastError
            );
        }

        throw new IllegalArgumentException("Ontology URL cannot be null or blank");
    }

    private List<String> createUrlCandidates(String url) {
        if (url == null || url.isBlank()) {
            return new ArrayList<>();
        }

        List<String> candidates = new ArrayList<>();
        if (url.contains(ONTOLOGY_HUB_EXTERNAL_BASE)) {
            candidates.addAll(createInternalCandidatesFromExternalUrl(url));
        } else {
            candidates.addAll(createInternalCandidatesForInternalUrl(url));
        }

        if (!candidates.contains(url)) {
            candidates.add(url);
        }
        return candidates;
    }

    private List<String> createInternalCandidatesFromExternalUrl(String url) {
        List<String> candidates = new ArrayList<>();
        for (String internalBase : ONTOLOGY_HUB_INTERNAL_CANDIDATES) {
            String candidate = url.replace(ONTOLOGY_HUB_EXTERNAL_BASE, internalBase);
            if (!candidate.isBlank() && !candidates.contains(candidate)) {
                candidates.add(candidate);
            }
        }
        return candidates;
    }

    private List<String> createInternalCandidatesForInternalUrl(String url) {
        List<String> candidates = new ArrayList<>();
        for (String internalBase : ONTOLOGY_HUB_INTERNAL_CANDIDATES) {
            if (url.contains(internalBase)) {
                addReplacementCandidates(url, internalBase, candidates);
                break;
            }
        }
        return candidates;
    }

    private void addReplacementCandidates(String url, String internalBase, List<String> candidates) {
        for (String replacementBase : ONTOLOGY_HUB_INTERNAL_CANDIDATES) {
            if (!replacementBase.equals(internalBase)) {
                String candidate = url.replace(internalBase, replacementBase);
                if (!candidate.isBlank() && !candidates.contains(candidate)) {
                    candidates.add(candidate);
                }
            }
        }
    }

    private Model loadModel(String modelUrl) {
        try {
            return RDFDataMgr.loadModel(modelUrl);
        } catch (org.apache.jena.riot.RiotException firstError) {
            // Fallback for ontology endpoints serving N3 with weak/incorrect content-type metadata.
            try (InputStream ontologyStream = URI.create(modelUrl).toURL().openStream()) {
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
            return url.replace(ONTOLOGY_HUB_EXTERNAL_BASE, ONTOLOGY_HUB_INTERNAL_BASE);
        }
        return url;
    }
}
