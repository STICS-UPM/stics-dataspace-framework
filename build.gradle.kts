plugins {
    `java-library`
    alias(libs.plugins.edc.build)
}

repositories {
    mavenCentral()
    mavenLocal()
}

allprojects {
    group = "com.pionera.assetfilter"
    version = "1.0.0"

    apply(plugin = "org.eclipse.edc.edc-build")

    configure<org.eclipse.edc.plugins.edcbuild.extensions.BuildExtension> {
        publish.set(false)
    }

    configure<CheckstyleExtension> {
        configFile = rootProject.file("resources/edc-checkstyle-config.xml")
        configDirectory.set(rootProject.file("resources"))
    }
}
