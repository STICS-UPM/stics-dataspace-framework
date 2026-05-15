/*
 *  Copyright (c) 2026 Pionera
 *
 *  This program and the accompanying materials are made available under the
 *  terms of the Apache License, Version 2.0 which is available at
 *  https://www.apache.org/licenses/LICENSE-2.0
 *
 *  SPDX-License-Identifier: Apache-2.0
 *
 *  Contributors:
 *       Pionera - initial API and implementation
 *
 */

package com.pionera.assetfilter.contracts;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.eclipse.edc.spi.monitor.Monitor;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

class ContractSequenceStore {
    private final ObjectMapper mapper;
    private final Monitor monitor;
    private final Path storagePath;

    private final Map<String, Long> countersByUser = new HashMap<>();

    ContractSequenceStore(ObjectMapper mapper, Monitor monitor, String storageFilePath) {
        this.mapper = mapper;
        this.monitor = monitor;
        this.storagePath = Path.of(storageFilePath);
        load();
    }

    synchronized long allocateNext(String userId) {
        var key = normalizeUserId(userId);
        var current = countersByUser.getOrDefault(key, 0L);
        var next = current + 1;
        countersByUser.put(key, next);
        persist();
        return next;
    }

    synchronized long peekNext(String userId) {
        var key = normalizeUserId(userId);
        var current = countersByUser.getOrDefault(key, 0L);
        return current + 1;
    }

    synchronized void commitAtLeast(String userId, long index) {
        var key = normalizeUserId(userId);
        var current = countersByUser.getOrDefault(key, 0L);
        if (index > current) {
            countersByUser.put(key, index);
            persist();
        }
    }

    private String normalizeUserId(String userId) {
        if (userId == null || userId.isBlank()) {
            return "user";
        }
        return userId.trim().toLowerCase();
    }

    private void load() {
        try {
            if (!Files.exists(storagePath)) {
                return;
            }
            var raw = Files.readString(storagePath, StandardCharsets.UTF_8);
            if (raw == null || raw.isBlank()) {
                return;
            }
            var loaded = mapper.readValue(raw, new TypeReference<Map<String, Long>>() {});
            countersByUser.clear();
            countersByUser.putAll(loaded);
            monitor.info("Loaded contract sequence counters from " + storagePath);
        } catch (Exception e) {
            monitor.warning("Failed to load contract sequence counters: " + e.getMessage());
        }
    }

    private void persist() {
        try {
            var parent = storagePath.getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            var raw = mapper.writerWithDefaultPrettyPrinter().writeValueAsString(countersByUser);
            Files.writeString(storagePath, raw, StandardCharsets.UTF_8);
        } catch (IOException e) {
            monitor.warning("Failed to persist contract sequence counters: " + e.getMessage());
        }
    }
}
