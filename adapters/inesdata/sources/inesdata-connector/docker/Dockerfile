FROM eclipse-temurin:17-jre-jammy
ARG CONNECTOR_JAR

# System env vars
ENV USER_GROUP=connectorgroup
ENV USER_NAME=connectoruser
ENV JVM_ARGS=""
ENV CONNECTOR_HOME=/opt/connector
ENV CONNECTOR_RESOURCES=${CONNECTOR_HOME}/resources

# Add the user who executes the connector without interactive prompts.
RUN addgroup ${USER_GROUP} && adduser --gecos "" --no-create-home --disabled-password --ingroup ${USER_GROUP} ${USER_NAME}

# Create the connector and resources directories
RUN mkdir -p ${CONNECTOR_HOME}
RUN mkdir -p ${CONNECTOR_RESOURCES}

# Work with the minimum rights
RUN chown -R ${USER_NAME}:0 ${CONNECTOR_HOME} \
    && chmod -R g=u ${CONNECTOR_HOME}

# The init-db container uses psql during pod startup; prefer HTTPS Ubuntu mirrors
# with retries to avoid transient HTTP mirror failures during image builds.
RUN set -eux; \
    sed -i 's|http://archive.ubuntu.com/ubuntu/|https://archive.ubuntu.com/ubuntu/|g; s|http://security.ubuntu.com/ubuntu/|https://security.ubuntu.com/ubuntu/|g' /etc/apt/sources.list; \
    apt-get update -o Acquire::Retries=5; \
    apt-get install -y --no-install-recommends postgresql-client; \
    rm -rf /var/lib/apt/lists/*

# User by default
USER ${USER_NAME} 

# Set the workdir
WORKDIR ${CONNECTOR_HOME}

# Copy connector
COPY $CONNECTOR_JAR connector.jar
COPY resources/* ${CONNECTOR_RESOURCES}/


# Use "exec" for Kubernetes graceful termination (SIGINT) to reach JVM.
ENTRYPOINT [ "sh", "-c", \
    "exec java $JVM_ARGS -jar connector.jar"]
