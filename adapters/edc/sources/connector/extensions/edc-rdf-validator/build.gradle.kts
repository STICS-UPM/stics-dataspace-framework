plugins {
    `java-library`
}

dependencies {
    implementation(libs.edc.web.spi)
    implementation(libs.edc.control.plane.spi)
    implementation(libs.edc.validator.spi)
    implementation("org.glassfish.jersey.media:jersey-media-multipart:2.41")
    implementation("org.apache.jena:apache-jena-libs:5.1.0")
}
