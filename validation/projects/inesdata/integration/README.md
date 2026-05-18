# Integración INESData

Este directorio contiene el catálogo canónico de flujos de integración INESData
para A5.2/E5.2.

El catálogo no define secretos ni credenciales. Solo declara casos, alcance,
trazabilidad, specs Playwright y variables runtime necesarias para activar
comportamientos de validación ya controlados por el framework.

## Relación con `validation/ui`

- `validation/ui/adapters/inesdata/specs/` contiene la implementación
  Playwright.
- `validation/projects/inesdata/integration/test_cases.yaml` contiene la
  trazabilidad funcional y de auditoría de esos flujos.
- `validation/ui/test_cases.yaml` queda reservado para checks técnicos comunes:
  soporte del portal y operaciones auxiliares como MinIO.

Level 6 usa este catálogo al enriquecer reportes UI y al construir el
`catalog_alignment` de las evidencias generadas.
