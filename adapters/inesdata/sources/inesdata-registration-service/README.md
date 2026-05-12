# Registration Service

This application is designed to manage and federate the participant catalog through a centralized service called **RegistrationService**. This service facilitates participant management via a RESTful API, providing specific endpoints to retrieve and modify participant information. The endpoints are structured with varying access levels to ensure that critical operations can only be performed by users with the `ADMIN` role.

## API Categories
`RegistrationService` offers two main categories of RESTful API endpoints:

- **Public Endpoints**: Accessible by connectors to retrieve participant information.
- **Administrative Endpoints**: Accessible only by users with the `dataspace-admin` role for participant management tasks.

## Authentication Tokens
To ensure secure access, the API utilizes two types of tokens:

- **Connector Token**: Used by connectors to authenticate requests to the `/participants` endpoint.
- **User Token (ADMIN Role)**: Ensures that only users with the `dataspace-admin` role can access administrative endpoints.

By adhering to these authentication protocols, the system ensures that sensitive operations are restricted to authorized personnel, enhancing the security and integrity of participant management.

## Disclaimer
Este trabajo ha recibido financiación del proyecto INESData (Infraestructura para la INvestigación de ESpacios de DAtos distribuidos en UPM), un proyecto financiado en el contexto de la convocatoria UNICO I+D CLOUD del Ministerio para la Transformación Digital y de la Función Pública en el marco del PRTR financiado por Unión Europea (NextGenerationEU)