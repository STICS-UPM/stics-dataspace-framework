package org.upm.inesdata.validator.example;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Base64;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.upm.inesdata.validator.dto.RdfValidationRequest;
import org.upm.inesdata.validator.dto.RdfValidationResponse;

/**
 * Ejemplo de integración en el Consumer.
 *
 * Este código muestra cómo hacer una solicitud de validación RDF
 * al endpoint POST /public/validation/rdf después de completar
 * una transferencia de datos.
 *
 * IMPORTANTE: Este es un ejemplo. Adapta según tu contexto.
 */
public class RdfValidationClientExample {

    private static final HttpClient HTTP_CLIENT = HttpClient.newHttpClient();
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * Valida datos RDF después de completar la transferencia.
     *
     * @param consumerApiUrl URL base del consumer (ej: http://localhost:7080)
     * @param transferId ID de la transferencia
     * @param rdfData Contenido RDF (bytes)
     * @param rdfFormat Formato RDF (TURTLE, RDFXML, etc.)
     * @return RdfValidationResponse con resultado
     */
    public static RdfValidationResponse validateRdfAfterTransfer(
            String consumerApiUrl,
            String transferId,
            byte[] rdfData,
            String rdfFormat
    ) throws IOException, InterruptedException {

        // 1. Codificar datos en base64
        String rdfBase64 = Base64.getEncoder().encodeToString(rdfData);

        // 2. Crear request
        RdfValidationRequest request = new RdfValidationRequest(
                transferId,
                rdfBase64,
                rdfFormat,
                "http://ontology-hub:3333/ontologies/default.n3",  // ontología por defecto
                "http://ontology-hub:3333/shacl/default.ttl"       // SHACL por defecto
        );

        // 3. Serializar a JSON
        String jsonPayload = MAPPER.writeValueAsString(request);

        // 4. Crear HTTP request
        HttpRequest httpRequest = HttpRequest.newBuilder()
                .uri(URI.create(consumerApiUrl + "/public/validation/rdf"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(jsonPayload))
                .build();

        // 5. Enviar request
        HttpResponse<String> httpResponse = HTTP_CLIENT.send(
                httpRequest,
                HttpResponse.BodyHandlers.ofString()
        );

        // 6. Parsear response
        RdfValidationResponse response = MAPPER.readValue(
                httpResponse.body(),
                RdfValidationResponse.class
        );

        return response;
    }

    /**
     * Variante avanzada: validación con ontología y SHACL personalizados.
     */
    public static RdfValidationResponse validateRdfWithCustomUrls(
            String consumerApiUrl,
            String transferId,
            byte[] rdfData,
            String rdfFormat,
            String ontologyUrl,
            String shaclUrl
    ) throws IOException, InterruptedException {

        String rdfBase64 = Base64.getEncoder().encodeToString(rdfData);

        RdfValidationRequest request = new RdfValidationRequest(
                transferId,
                rdfBase64,
                rdfFormat,
                ontologyUrl,
                shaclUrl
        );

        String jsonPayload = MAPPER.writeValueAsString(request);

        HttpRequest httpRequest = HttpRequest.newBuilder()
                .uri(URI.create(consumerApiUrl + "/public/validation/rdf"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(jsonPayload))
                .build();

        HttpResponse<String> httpResponse = HTTP_CLIENT.send(
                httpRequest,
                HttpResponse.BodyHandlers.ofString()
        );

        return MAPPER.readValue(
                httpResponse.body(),
                RdfValidationResponse.class
        );
    }

    /**
     * Ejemplo de uso en un TransferProcess listener del consumer.
     */
    public static void exampleUsageInTransferCompleteHandler(
            String consumerApiUrl,
            String transferId,
            byte[] receivedRdfData
    ) {
        try {
            // Validar datos después de transferencia
            RdfValidationResponse result = validateRdfAfterTransfer(
                    consumerApiUrl,
                    transferId,
                    receivedRdfData,
                    "TURTLE"
            );

            // Procesar resultado
            if (result.isValid()) {
                System.out.println("✅ Validación exitosa: " + result.getMessage());
                // TODO: Procesamiento de datos válidos
            } else {
                System.out.println("❌ Validación fallida: " + result.getMessage());
                // TODO: Procesamiento de datos inválidos
            }

        } catch (IOException | InterruptedException e) {
            System.err.println("💥 Error durante validación: " + e.getMessage());
            e.printStackTrace();
        }
    }

    /**
     * Ejemplo con manejo de errores más robusto.
     */
    public static void robustValidationExample(
            String consumerApiUrl,
            String transferId,
            byte[] rdfData
    ) {
        try {
            // Timeout de 30 segundos
            RdfValidationResponse response = validateRdfAfterTransfer(
                    consumerApiUrl,
                    transferId,
                    rdfData,
                    "TURTLE"
            );

            logValidationResult(response);

        } catch (IOException e) {
            System.err.println("Network error during validation: " + e.getMessage());
            // Retry logic here...
        } catch (InterruptedException e) {
            System.err.println("Validation request interrupted: " + e.getMessage());
            Thread.currentThread().interrupt();
        }
    }

    /**
     * Logger de resultados.
     */
    private static void logValidationResult(RdfValidationResponse response) {
        System.out.println("\n" +
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" +
                "📋 RDF Validation Result\n" +
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" +
                "Transfer ID: " + response.getTransferId() + "\n" +
                "Valid: " + (response.isValid() ? "✅ YES" : "❌ NO") + "\n" +
                "Message: " + response.getMessage() + "\n" +
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        );
    }
}

