plugins {
    `java-library`
    id("application")
    alias(libs.plugins.shadow)
}

dependencies {
    implementation(libs.edc.data.plane.spi)
    implementation(libs.edc.web.spi)

    runtimeOnly(project(":connector"))
}

application {
    mainClass.set("org.eclipse.edc.boot.system.runtime.BaseRuntime")
}

val distTar = tasks.getByName("distTar")
val distZip = tasks.getByName("distZip")

tasks.withType<CreateStartScripts> {
    dependsOn(":connector:shadowJar")
}

tasks.withType<com.github.jengelman.gradle.plugins.shadow.tasks.ShadowJar> {
    mergeServiceFiles()
    archiveFileName.set("connector.jar")
    dependsOn(distTar, distZip)
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
}
