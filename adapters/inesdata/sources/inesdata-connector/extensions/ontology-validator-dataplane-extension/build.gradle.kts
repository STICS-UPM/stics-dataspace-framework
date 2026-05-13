plugins {
    `java-library`
    id("com.gmv.inesdata.edc-application")
}

dependencies {
    api(libs.edc.api.core)
    api(project(":spi:vocabulary-spi"))
    api(project(":extensions:vocabulary-shared-api"))

    implementation(project(":extensions:ontology-validator"))
    implementation("org.glassfish.jersey.media:jersey-media-multipart:2.41")
    implementation("org.apache.jena:apache-jena-libs:5.1.0")
    implementation(libs.edc.control.plane.spi)
    implementation(libs.edc.data.plane.spi)
    implementation(libs.edc.lib.validator)
    implementation(libs.edc.transaction.spi)
    implementation(libs.edc.transaction.datasource.spi)

    testImplementation(libs.assertj)
    testImplementation(libs.edc.core.junit)
}
