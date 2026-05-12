# Targets de validación

Esta carpeta contiene ejemplos de configuración para entornos que el framework
no despliega, pero sí puede validar desde `G - Validate target` en modo
`validation-only`.

Reglas:

- sube solo ficheros `*.example.yaml`;
- no subas targets reales con URLs privadas, usuarios, tokens o contraseñas;
- las credenciales deben resolverse por prompt interactivo seguro, variables de
  entorno o secret manager;
- los targets externos no habilitan `Levels 1-5`.
- el runner actual no ejecuta limpieza, escrituras ni acciones destructivas.
- solo ejecuta specs Playwright reales `*.spec.ts` o `*.spec.js`; los ficheros
  `*.example.*` son plantillas y no se ejecutan.

Ejemplo recomendado:

```text
inesdata-production.example.yaml
```

Fichero local real, ignorado por Git:

```text
inesdata-production.yaml
```
