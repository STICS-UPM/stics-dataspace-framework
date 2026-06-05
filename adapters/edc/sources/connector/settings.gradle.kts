rootProject.name = "asset-filter-template"

pluginManagement {
    repositories {
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        mavenCentral()
        mavenLocal()
    }
}

include(":connector")
include(":provider-proxy-data-plane")
include(":final-connector")

// validation-environment-edc-rdf-overlay
include(":extensions:edc-rdf-validator")
include(":extensions:edc-rdf-validator-dataplane")
include(":extensions:edc-rdf-validation-api")
