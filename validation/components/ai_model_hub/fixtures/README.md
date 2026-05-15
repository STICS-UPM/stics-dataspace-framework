# Fixtures de AI Model Hub

Esta carpeta queda reservada para fixtures auxiliares de `AI Model Hub` que no
sean datasets fuente.

Los datasets de validación se sincronizan en `Level 5` bajo:

```text
validation/datasets/sources/
```

Las suites pueden derivar muestras o estructuras de benchmark durante la
ejecución, pero esas salidas se guardan como evidencias en `experiments/` y no
como datasets reducidos versionados dentro de `validation/components/`.
