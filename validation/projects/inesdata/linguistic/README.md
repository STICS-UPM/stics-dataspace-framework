# Suite lingüística INESData

Scaffold read-only para futuras validaciones del espacio de datos lingüístico de
INESData externo.

La suite debe empezar con casos `read-only`, por ejemplo:

- acceso al portal;
- visibilidad del catálogo;
- búsqueda o filtrado no destructivo;
- comprobación de metadatos esperados.

Las pruebas que creen, editen o borren datos deben quedar fuera del perfil por
defecto y requerir aprobación explícita.
