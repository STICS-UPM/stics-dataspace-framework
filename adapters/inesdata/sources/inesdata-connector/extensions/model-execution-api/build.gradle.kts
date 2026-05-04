plugins {
    `java-library`
    id("com.gmv.inesdata.edc-application")
    id("com.gmv.inesdata.edc-swagger")
}

dependencies {
    api(libs.edc.spi.core)
    implementation(libs.edc.web.spi)
    implementation(libs.edc.connector.core)
    implementation(libs.edc.api.core)
    implementation(libs.edc.api.management.config)
    implementation(libs.edc.lib.util)
    implementation(libs.swagger.annotations.jakarta)
    implementation(libs.jakarta.rsApi)
    implementation(libs.edc.api.lib)
}

edcBuild {
    swagger {
        apiGroup.set("management-api")
    }
}
