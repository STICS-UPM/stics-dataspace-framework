# Specs Playwright lingüísticos

Coloca aquí specs Playwright de la suite lingüística.

Convención recomendada:

```text
inesdata_ling_01_portal_access.spec.ts
inesdata_ling_02_catalog_visible.spec.ts
```

Los specs deben leer URLs y credenciales desde el runtime del target, no desde
valores hardcodeados.

Los ficheros `*.example.*` son plantillas y no se ejecutan. Para activar una
prueba real, crea un fichero `*.spec.ts` o `*.spec.js` y habilita la suite desde
`project_suites` en el target.
