FROM eclipse-temurin:17-jre

WORKDIR /opt/connector

ARG CONNECTOR_JAR=final-connector/build/libs/connector.jar

COPY ${CONNECTOR_JAR} /opt/connector/connector.jar

EXPOSE 19191 19192 19193 19194 19195 19196 19291

ENTRYPOINT ["java", "-jar", "/opt/connector/connector.jar"]
