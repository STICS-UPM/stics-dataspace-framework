# Recursos compartidos de INESData

Usa esta carpeta para helpers, fixtures y documentación reutilizable por varias
suites de INESData.

El helper `target-runtime.ts` permite que los specs Playwright lean el runtime
del target externo mediante `INESDATA_TARGET_RUNTIME_FILE` y eviten URLs
hardcodeadas.

No guardes aquí:

- credenciales;
- tokens;
- datos personales;
- URLs privadas no públicas;
- resultados de ejecución.
