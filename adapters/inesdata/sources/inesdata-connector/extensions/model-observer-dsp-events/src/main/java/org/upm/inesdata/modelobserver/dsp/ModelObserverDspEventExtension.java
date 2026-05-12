package org.upm.inesdata.modelobserver.dsp;

import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.runtime.metamodel.annotation.Setting;
import org.eclipse.edc.spi.event.Event;
import org.eclipse.edc.spi.event.EventRouter;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;

@Extension(value = ModelObserverDspEventExtension.NAME)
public class ModelObserverDspEventExtension implements ServiceExtension {
    public static final String NAME = "Model Observer DSP Events Extension";

    @Setting(value = "Enable or disable journal emission for model observer DSP events.", defaultValue = "true")
    public static final String JOURNAL_ENABLED = "model.observer.journal.enabled";

    @Setting(value = "Base URL for the model observer journal backend.", defaultValue = "")
    public static final String JOURNAL_BASE_URL = "model.observer.journal.baseurl";

    @Setting(value = "Relative path used to publish single model observer events.", defaultValue = "/api/model-observer/events")
    public static final String JOURNAL_EVENTS_PATH = "model.observer.journal.events.path";

    @Setting(value = "Source component value written into emitted model observer events.", defaultValue = "inesdata-connector")
    public static final String SOURCE_COMPONENT = "model.observer.source.component";

    @Inject
    private EventRouter eventRouter;

    @Inject
    private Monitor monitor;

    @Override
    public String name() {
        return NAME;
    }

    @Override
    public void initialize(ServiceExtensionContext context) {
        boolean journalEnabled = Boolean.parseBoolean(String.valueOf(context.getSetting(JOURNAL_ENABLED, "true")));
        String journalBaseUrl = String.valueOf(context.getSetting(JOURNAL_BASE_URL, ""));
        String journalEventsPath = String.valueOf(context.getSetting(JOURNAL_EVENTS_PATH, "/api/model-observer/events"));
        String sourceComponent = String.valueOf(context.getSetting(SOURCE_COMPONENT, "inesdata-connector"));

        var mapper = new ModelObserverDspEventMapper(context.getParticipantId(), sourceComponent);
        var journalClient = new ModelObserverJournalClient(monitor, journalEnabled, journalBaseUrl, journalEventsPath);
        var subscriber = new ModelObserverDspEventSubscriber(monitor, mapper, journalClient);

        eventRouter.register(Event.class, subscriber);
        eventRouter.registerSync(Event.class, subscriber);

        if (!journalEnabled) {
            monitor.warning("Model observer DSP journal emission is disabled by configuration.");
        } else if (journalBaseUrl == null || journalBaseUrl.isBlank()) {
            monitor.warning("Model observer DSP extension initialized without journal base URL. Events will only be logged locally.");
        } else {
            monitor.info("Model observer DSP extension initialized with journal endpoint " + journalBaseUrl + journalEventsPath);
        }
    }
}