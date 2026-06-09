/*
 *  Copyright (c) 2024 Bayerische Motoren Werke Aktiengesellschaft (BMW AG)
 *
 *  This program and the accompanying materials are made available under the
 *  terms of the Apache License, Version 2.0 which is available at
 *  https://www.apache.org/licenses/LICENSE-2.0
 *
 *  SPDX-License-Identifier: Apache-2.0
 *
 *  Contributors:
 *       Bayerische Motoren Werke Aktiengesellschaft (BMW AG) - initial API and implementation
 *
 */

package org.upm.inesdata.extendeddataplanepublic;

import org.eclipse.edc.connector.dataplane.spi.Endpoint;
import org.eclipse.edc.connector.dataplane.spi.iam.PublicEndpointGeneratorService;
import org.eclipse.edc.runtime.metamodel.annotation.Configuration;
import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.runtime.metamodel.annotation.Setting;
import org.eclipse.edc.runtime.metamodel.annotation.SettingContext;
import org.eclipse.edc.runtime.metamodel.annotation.Settings;
import org.eclipse.edc.spi.system.Hostname;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;
import org.eclipse.edc.web.spi.configuration.ApiContext;

/**
 * Adds the INESData HttpData public endpoint generator.
 *
 * The launcher already loads EDC's data-plane-public-api-v2 extension, so this extension must not register the
 * public web context or controller again. It only contributes the HttpData endpoint mapping used to resolve EDRs
 * for model execution assets.
 */
@Extension(value = ExtendedDataPlanePublicApiExtension.NAME)
public class ExtendedDataPlanePublicApiExtension implements ServiceExtension {
    public static final String NAME = "INESData HttpData public endpoint generator";

    private static final int DEFAULT_PUBLIC_PORT = 8185;
    private static final String DEFAULT_PUBLIC_PATH = "/api/v2/public";

    @Setting(value = "Base url of the public API endpoint without the trailing slash. This should correspond to the values configured " +
            "in '" + DEFAULT_PUBLIC_PORT + "' and '" + DEFAULT_PUBLIC_PATH + "'.", defaultValue = "http://<HOST>:" + DEFAULT_PUBLIC_PORT + DEFAULT_PUBLIC_PATH)
    private static final String PUBLIC_ENDPOINT = "edc.dataplane.api.public.baseurl";

    @Configuration
    private PublicApiConfiguration apiConfiguration;

    @Inject
    private PublicEndpointGeneratorService generatorService;

    @Inject
    private Hostname hostname;

    @Override
    public String name() {
        return NAME;
    }

    @Override
    public void initialize(ServiceExtensionContext context) {
        var publicEndpoint = context.getSetting(PUBLIC_ENDPOINT, null);
        if (publicEndpoint == null) {
            publicEndpoint = "http://%s:%d%s".formatted(hostname.get(), apiConfiguration.port(), apiConfiguration.path());
            context.getMonitor().warning("Config property '%s' was not specified, the default '%s' will be used.".formatted(PUBLIC_ENDPOINT, publicEndpoint));
        }
        var endpoint = Endpoint.url(publicEndpoint);
        generatorService.addGeneratorFunction("HttpData", dataAddress -> endpoint);
    }

    @Settings
    record PublicApiConfiguration(
            @Setting(key = "web.http." + ApiContext.PUBLIC + ".port", description = "Port for " + ApiContext.PUBLIC + " api context", defaultValue = DEFAULT_PUBLIC_PORT + "")
            int port,
            @Setting(key = "web.http." + ApiContext.PUBLIC + ".path", description = "Path for " + ApiContext.PUBLIC + " api context", defaultValue = DEFAULT_PUBLIC_PATH)
            String path
    ) {
    }
}
