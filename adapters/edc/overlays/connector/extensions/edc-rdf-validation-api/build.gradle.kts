plugins {
    `java-library`
}

dependencies {
    implementation(project(":extensions:edc-rdf-validator-dataplane"))
    implementation(libs.edc.control.plane.api)
    implementation(libs.edc.control.plane.spi)
    implementation(libs.edc.web.spi)
    implementation(libs.edc.json.ld.spi)
    implementation(libs.edc.lib.transform)
    implementation(libs.edc.transfer.process.api)
    implementation(libs.edc.transaction.spi)
    implementation(libs.edc.transaction.datasource.spi)
}
