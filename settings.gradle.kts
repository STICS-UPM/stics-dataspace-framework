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
