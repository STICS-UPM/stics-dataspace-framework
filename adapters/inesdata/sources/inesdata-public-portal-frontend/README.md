# Inesdata Public Portal Frontend

## Requirements

- NodeJS 20.11+

## Environment variables

Environment configuration is used to add dynamic properties to the project. For dynamic properties substitution it must be added in the following configuration files:

- Add it to the `runtime` attribute of `environments/environment.[prod].ts` file. In `prod` file add it with blank value.
- Add it to the `runtime` attribute of `environments/runtime-environment-template.json` file.
- Add the environment variables to the `Dockerfile`.
- Use of the new property: `${environment.runtime.api.url}`

Note: In localhost deployment it will show an error because the `/assets/config/runtime-environment.json` file does not exists, but it will work fine.

# BUILD

Run `ng build` to build the project or `npm run build`. The build artifacts will be stored in the `dist/` directory. Use the `--prod` flag for a production build (`-- --prod` when using `npm run build`).

Important: Build to prod using the additional parameter `--base-href /angular-quickstart/` if your app are not served in the root context

## Docker

The Dockerfile is based on a nginx image.

Build the image using the following command:

```
docker build --tag upm-inesdata/inesdata-public-portal-frontend:0.1.0 -f docker/Dockerfile .
```

Run it locally by using the env.list with environment:

```
docker run --name inesdata-public-portal-frontend -p 80:80  --env-file ./docker/env-localhost/env.list -d upm-inesdata/inesdata-public-portal-frontend:0.1.0
```

## Disclaimer

Este trabajo ha recibido financiación del proyecto INESData (Infraestructura para la INvestigación de ESpacios de DAtos distribuidos en UPM), un proyecto financiado en el contexto de la convocatoria UNICO I+D CLOUD del Ministerio para la Transformación Digital y de la Función Pública en el marco del PRTR financiado por Unión Europea (NextGenerationEU)