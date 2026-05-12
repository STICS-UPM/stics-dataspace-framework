# Specs Playwright de movilidad

Coloca aquí specs Playwright de la suite de movilidad cuando el owner funcional
defina los flujos.

Convención recomendada:

```text
inesdata_mob_01_portal_access.spec.ts
inesdata_mob_02_catalog_visible.spec.ts
```

Los ficheros `*.example.*` son plantillas y no se ejecutan. Para activar una
prueba real, crea un fichero `*.spec.ts` o `*.spec.js` y habilita la suite desde
`project_suites` en el target.
