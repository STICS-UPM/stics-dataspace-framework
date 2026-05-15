plugins {
    `java-library`
    id("application")
    alias(libs.plugins.shadow)
}

dependencies {
    implementation(libs.edc.runtime.core)
    implementation(libs.edc.connector.core)
    implementation(libs.edc.control.api.configuration)
    implementation(libs.edc.control.plane.api.client)
    implementation(libs.edc.control.plane.api)
    implementation(libs.edc.control.plane.core)
    implementation(libs.edc.token.core)
    implementation(libs.edc.dsp)
    implementation(libs.edc.http)
    implementation(libs.edc.configuration.filesystem)
    implementation(libs.edc.iam.mock)
    implementation(libs.edc.management.api)
    implementation(libs.edc.transfer.data.plane.signaling)
    implementation(libs.edc.validator.data.address.http.data)

    implementation(libs.edc.edr.cache.api)
    implementation(libs.edc.edr.store.core)
    implementation(libs.edc.edr.store.receiver)

    implementation(libs.edc.data.plane.selector.api)
    implementation(libs.edc.data.plane.selector.core)

    implementation(libs.edc.data.plane.self.registration)
    implementation(libs.edc.data.plane.signaling.api)
    implementation(libs.edc.data.plane.core)
    implementation(libs.edc.data.plane.http)
    implementation(libs.edc.data.plane.iam)

    implementation(libs.edc.web.spi)
}

application {
    mainClass.set("org.eclipse.edc.boot.system.runtime.BaseRuntime")
}

val distTar = tasks.getByName("distTar")
val distZip = tasks.getByName("distZip")

tasks.withType<com.github.jengelman.gradle.plugins.shadow.tasks.ShadowJar> {
    mergeServiceFiles()
    archiveFileName.set("connector.jar")
    dependsOn(distTar, distZip)
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
}
