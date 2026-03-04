plugins {
    `java-library`
    id("application")
    alias(libs.plugins.shadow)
}

dependencies {
    implementation(libs.edc.data.plane.spi)
    implementation(libs.edc.web.spi)

    // Bring in all shared extensions and proxy behavior via existing modules
    runtimeOnly(project(":connector"))
    runtimeOnly(project(":provider-proxy-data-plane"))
}

application {
    mainClass.set("org.eclipse.edc.boot.system.runtime.BaseRuntime")
}

val distTar = tasks.getByName("distTar")
val distZip = tasks.getByName("distZip")

tasks.withType<CreateStartScripts> {
    dependsOn(":connector:shadowJar")
    dependsOn(":provider-proxy-data-plane:shadowJar")
}

tasks.withType<com.github.jengelman.gradle.plugins.shadow.tasks.ShadowJar> {
    mergeServiceFiles()
    archiveFileName.set("connector.jar")
    dependsOn(distTar, distZip)
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
}
