package org.upm.inesdata.modelobserver.dsp;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.ws.rs.client.Client;
import jakarta.ws.rs.client.ClientBuilder;
import jakarta.ws.rs.client.Entity;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.edc.spi.monitor.Monitor;

import java.util.Map;

public class ModelObserverJournalClient {
    private final Monitor monitor;
    private final boolean enabled;
    private final String targetUrl;
    private final Client client;
    private final ObjectMapper objectMapper;

    public ModelObserverJournalClient(Monitor monitor,
                                      boolean enabled,
                                      String journalBaseUrl,
                                      String journalEventsPath) {
        this.monitor = monitor;
        this.enabled = enabled;
        this.targetUrl = buildTargetUrl(journalBaseUrl, journalEventsPath);
        this.client = ClientBuilder.newClient();
        this.objectMapper = new ObjectMapper();
    }

    public boolean publish(Map<String, Object> event) {
        if (!enabled) {
            monitor.debug("Model observer journal client skipped publish because it is disabled.");
            return false;
        }

        if (targetUrl == null || targetUrl.isBlank()) {
            monitor.info("[MODEL-OBSERVER][LOCAL-ONLY] " + event);
            return false;
        }

        try (Response response = client.target(targetUrl)
                .request(MediaType.APPLICATION_JSON)
                .post(Entity.entity(objectMapper.writeValueAsString(event), MediaType.APPLICATION_JSON))) {
            if (response.getStatusInfo().getFamily() == Response.Status.Family.SUCCESSFUL) {
                return true;
            }

            var responseBody = response.hasEntity() ? response.readEntity(String.class) : "";
            monitor.warning("Model observer journal publish failed with status " + response.getStatus() + ": " + responseBody);
            return false;
        } catch (Exception exception) {
            monitor.warning("Model observer journal publish failed: " + exception.getMessage());
            return false;
        }
    }

    private String buildTargetUrl(String journalBaseUrl, String journalEventsPath) {
        if (journalBaseUrl == null || journalBaseUrl.isBlank()) {
            return "";
        }

        var normalizedBaseUrl = journalBaseUrl.endsWith("/") ? journalBaseUrl.substring(0, journalBaseUrl.length() - 1) : journalBaseUrl;
        var normalizedPath = journalEventsPath == null || journalEventsPath.isBlank()
                ? "/api/model-observer/events"
                : (journalEventsPath.startsWith("/") ? journalEventsPath : "/" + journalEventsPath);
        return normalizedBaseUrl + normalizedPath;
    }
}