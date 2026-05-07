package org.upm.inesdata.modelobserver.dsp;

import org.eclipse.edc.spi.event.Event;
import org.eclipse.edc.spi.event.EventEnvelope;
import org.eclipse.edc.spi.event.EventSubscriber;
import org.eclipse.edc.spi.monitor.Monitor;

import java.util.Map;

public class ModelObserverDspEventSubscriber implements EventSubscriber {
    private final Monitor monitor;
    private final ModelObserverDspEventMapper mapper;
    private final ModelObserverJournalClient journalClient;

    public ModelObserverDspEventSubscriber(Monitor monitor,
                                           ModelObserverDspEventMapper mapper,
                                           ModelObserverJournalClient journalClient) {
        this.monitor = monitor;
        this.mapper = mapper;
        this.journalClient = journalClient;
    }

    @Override
    public <E extends Event> void on(EventEnvelope<E> event) {
        Map<String, Object> modelObserverEvent = mapper.map(event);
        if (modelObserverEvent == null) {
            return;
        }

        var published = journalClient.publish(modelObserverEvent);
        if (!published) {
            monitor.warning("Model observer DSP event was not published to journal. Event type=" + modelObserverEvent.get("eventType"));
        }
    }
}