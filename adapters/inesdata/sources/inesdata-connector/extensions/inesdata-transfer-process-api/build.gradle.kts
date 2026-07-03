plugins {
    `java-library`
    id("com.gmv.inesdata.edc-application")
    id("com.gmv.inesdata.edc-swagger")
}

dependencies {
    api(libs.edc.spi.core)
    implementation(libs.edc.control.plane.spi)
    implementation(project(":extensions:ontology-validator-dataplane-extension"))
    implementation(libs.edc.transfer.process.api)
    implementation(libs.edc.api.management.lib)
    implementation(libs.edc.web.spi)

    implementation(libs.edc.connector.core)
    implementation(libs.edc.api.core)
    implementation(libs.edc.api.lib)
    implementation(libs.edc.lib.util)
    implementation(libs.edc.lib.transform)
    implementation(libs.edc.dsp.api.configuration)
    implementation(libs.edc.api.management.config)
    implementation(libs.edc.spi.jsonld)
    implementation(libs.swagger.annotations.jakarta)
    implementation(libs.edc.transaction.spi)
    implementation(libs.edc.transaction.datasource.spi)
    implementation(libs.edc.lib.validator)
    implementation(libs.edc.validator.spi)
    implementation(libs.swagger.annotations.jakarta)
    runtimeOnly(libs.edc.json.ld.lib)
}

edcBuild {
    swagger {
        apiGroup.set("management-api")
    }
}
