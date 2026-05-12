package org.upm.inesdata.validator.pipeline;

import org.eclipse.edc.connector.dataplane.spi.pipeline.DataSource;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;

class SpooledPart implements DataSource.Part {
    final String name;
    final String mediaType;
    final Path path;

    SpooledPart(String name, String mediaType, Path path) {
        this.name = name;
        this.mediaType = mediaType;
        this.path = path;
    }

    @Override
    public String name() {
        return name;
    }

    @Override
    public InputStream openStream() {
        try {
            return Files.newInputStream(path);
        } catch (IOException e) {
            throw new RuntimeException("Cannot open spooled stream for part " + name, e);
        }
    }

    @Override
    public String mediaType() {
        return mediaType != null ? mediaType : "application/octet-stream";
    }

    void deleteQuietly() {
        try {
            Files.deleteIfExists(path);
        } catch (IOException ignored) {
        }
    }
}
