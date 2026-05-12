package org.upm.inesdata.registration_service.config;

import org.springdoc.core.models.GroupedOpenApi;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Swagger configuration class for grouping APIs.
 * Defines API groups for public and participant endpoints.
 * @author gmv
 */
@Configuration
public class SwaggerConfig {

    /**
     * Bean for public API group.
     *
     * @return GroupedOpenApi instance for public endpoints.
     */
    @Bean
    public GroupedOpenApi publicApi() {
        return GroupedOpenApi.builder()
            .group("public")
            .pathsToMatch("/public/**")
            .build();
    }

    /**
     * Bean for participant API group.
     *
     * @return GroupedOpenApi instance for participant endpoints.
     */
    @Bean
    public GroupedOpenApi participantApi() {
        return GroupedOpenApi.builder()
            .group("participants")
            .pathsToMatch("/participants/**")
            .build();
    }
}
