FROM eclipse-temurin:17-jre-alpine

# System env vars
ENV JAVA_OPTS=""
ENV USER_NAME=gmvuser
ENV USER_UID=200
ENV APP_HOME=/opt/registration-service

# Add the user who executes the app. The user belongs to the group with gui 0
RUN adduser -G root -s /bin/sh -D -u ${USER_UID} ${USER_NAME}

# Create the app directory
RUN mkdir -p ${APP_HOME}

# Copy the script of the entrypoint and resources
COPY ./docker/docker-entrypoint.sh ${APP_HOME}/docker-entrypoint.sh 

# Sets the minimum rights
RUN chown -R ${USER_NAME}:0 ${APP_HOME} \
    && chmod -R g=u ${APP_HOME} \
    && chmod ug+x ${APP_HOME}/docker-entrypoint.sh

# Avoiding exec docker-entrypoint error
RUN sed -i -e 's/\r$//' ${APP_HOME}/docker-entrypoint.sh

# Define the port of the container
EXPOSE 8080
 
# User by default
USER ${USER_NAME}  

# Script entrypoint for the container
WORKDIR ${APP_HOME}
ENTRYPOINT ["./docker-entrypoint.sh"]

# Copy the executable jar
COPY --chown="${USER_NAME}:0" ./build/libs/*.jar ${APP_HOME}/
RUN rm -f ${APP_HOME}/*plain.jar
RUN mv ${APP_HOME}/registration-service-*.jar ${APP_HOME}/registration-service.jar