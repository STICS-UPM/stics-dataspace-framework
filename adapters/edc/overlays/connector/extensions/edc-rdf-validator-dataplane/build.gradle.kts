plugins {
    `java-library`
}

dependencies {
    implementation(project(":extensions:edc-rdf-validator"))
    implementation(libs.edc.control.plane.spi)
    implementation(libs.edc.data.plane.spi)
    implementation(libs.edc.web.spi)
    implementation(libs.edc.transaction.spi)
    implementation(libs.edc.transaction.datasource.spi)
    implementation(libs.edc.lib.validator)
    implementation("org.glassfish.jersey.media:jersey-media-multipart:2.41")
    implementation("org.apache.jena:apache-jena-libs:5.1.0")
}
