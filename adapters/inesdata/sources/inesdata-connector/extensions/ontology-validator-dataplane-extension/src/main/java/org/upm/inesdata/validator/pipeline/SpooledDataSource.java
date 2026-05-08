package org.upm.inesdata.validator.pipeline;

import org.eclipse.edc.connector.dataplane.spi.pipeline.DataSource;
import org.eclipse.edc.connector.dataplane.spi.pipeline.StreamResult;

import java.util.List;
import java.util.stream.Stream;

class SpooledDataSource implements DataSource {
    final List<SpooledPart> parts;

    SpooledDataSource(List<SpooledPart> parts) {
        this.parts = parts;
    }

    @Override
    public StreamResult<Stream<DataSource.Part>> openPartStream() {
        return StreamResult.success(parts.stream().map(part -> (DataSource.Part) part));
    }

    @Override
    public void close() {
        cleanup();
    }

    void cleanup() {
        parts.forEach(SpooledPart::deleteQuietly);
    }
}
