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

package com.pionera.assetfilter.filter;

import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;
import org.eclipse.edc.spi.types.TypeManager;
import org.eclipse.edc.web.spi.WebService;

public class AssetFilterExtension implements ServiceExtension {

    @Inject
    private WebService webService;
    @Inject
    private TypeManager typeManager;
    @Inject
    private Monitor monitor;

    @Override
    public void initialize(ServiceExtensionContext context) {
        var config = context.getConfig();
        var hostname = config.getString("edc.hostname", "localhost");
        var managementPort = config.getInteger("web.http.management.port", 29193);
        var managementPath = config.getString("web.http.management.path", "/management");
        var managementBaseUrl = "http://" + hostname + ":" + managementPort + managementPath;

        webService.registerResource(new AssetFilterController(typeManager, monitor, managementBaseUrl));
    }
}
