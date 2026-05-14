# Visor de reportes de experimentos

El framework incluye un visor local para revisar resultados de validación sin
buscar manualmente carpetas ni abrir JSON largos por consola.

## Uso desde el menú

Ejecuta:

```bash
python3 main.py
```

Luego selecciona:

```text
E - View experiment reports
```

El framework lista los experimentos disponibles bajo `experiments/`, muestra un
resumen por adapter, topología, runtime de cluster, estado del dashboard y tipos
de reporte detectados, y permite abrir el experimento que necesites.

Además de los experimentos `experiment_<timestamp>`, el visor puede mostrar
evidencias opt-in generadas fuera de Level 6 cuando la carpeta incluye
`metadata.json` y artefactos reales como `results.json` o un reporte Playwright.
Esto permite incorporar evidencias A5.2 cerradas sin listar intentos
intermedios de depuración.

Los runners de componente que no producen Playwright también pueden aparecer en
el visor si guardan un JSON bajo `components/<componente>/<suite>/` con campos
`status` y `summary`. Este formato se usa para evidencias como `MH-MOB-01`,
donde el resultado principal es un benchmark reproducible por API.

En experimentos antiguos puede aparecer `Topology: not recorded` si el
artefacto `metadata.json` todavía no guardaba la topología. En ese caso,
`minikube` o `k3s` se muestran como `Cluster runtime`, no como topología. Los
experimentos nuevos guardan ambos campos por separado.

El campo `Dashboard status` resume hallazgos detectados por el visor, no
reemplaza el estado de ejecución del nivel. Por ejemplo, un `Level 6` puede
haber terminado correctamente y el dashboard mostrar `Warnings detected` o
`Issues detected` si hay warnings de estabilidad o suites con fallos
funcionales.

## Dashboard del experimento

La opción recomendada es:

```text
1 - Open experiment dashboard
```

El framework genera un índice HTML local en:

```text
experiments/experiment_<timestamp>/framework-report/index.html
```

Ese dashboard concentra:

- enlaces a reportes Playwright;
- resumen de Newman;
- resumen de Kafka;
- resumen de componentes;
- resumen de runners de componente con `status` y `summary`;
- alineación UNE 0087 cuando existe `une_0087_alignment.json`;
- estado del postflight local cuando existe;
- enlaces a artefactos JSON/TXT completos.

El dashboard no sustituye al reporte Playwright. Playwright mantiene su propio
reporte especializado y el dashboard del framework funciona como punto de
entrada del experimento.

## Alineación UNE 0087

La alineación UNE 0087 se genera como artefacto de apoyo, no como certificación
formal ni como bloqueo de Level 6. Para crearla sobre un experimento existente:

```bash
python3 -m framework.reporting.une_0087_alignment --experiment-dir experiments/<experiment_id>
```

También se pueden añadir evidencias externas del mismo cierre A5.2:

```bash
python3 -m framework.reporting.une_0087_alignment \
  --experiment-dir experiments/<experiment_id> \
  --evidence experiments/<other_evidence_dir>
```

El comando escribe `une_0087_alignment.json` y `une_0087_alignment.md` dentro
del experimento. Si existen, el dashboard los detecta automáticamente y muestra
un resumen por criterios cubiertos, parcialmente cubiertos y no cubiertos.

## Seguridad

El visor es de solo lectura. No ejecuta validaciones, no limpia datos, no borra
artefactos y no cambia la topología ni el adapter activo.

El servidor local se levanta únicamente en:

```text
127.0.0.1
```

No se usa `0.0.0.0`, por lo que los reportes no quedan expuestos directamente a
la red interna.

## Playwright

Si quieres abrir directamente un reporte Playwright, usa la opción:

```text
2 - Open Playwright report
```

El framework usa el mecanismo oficial de Playwright:

```bash
npx playwright show-report <report-path> --host 127.0.0.1 --port <free-port>
```

Esto permite navegar traces, screenshots y vídeos de forma más fiable que
abriendo `index.html` manualmente desde el explorador de archivos.

## Windows + WSL

En Windows + WSL, el framework intenta abrir la URL directamente en el navegador
predeterminado. Para reducir la carga manual, prueba estos mecanismos en orden:

- `wslview`, si está disponible.
- `cmd.exe /c start`, usando `/mnt/c/Windows/System32/cmd.exe` si `cmd.exe` no
  está en el `PATH`.
- `powershell.exe Start-Process`.
- `explorer.exe`.
- `xdg-open`, cuando exista un escritorio Linux disponible.

Si ningún mecanismo está disponible, el framework imprime la URL local para
abrirla manualmente.
