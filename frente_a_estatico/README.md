# Frente A: análisis estático del código

Detecta patrones peligrosos en el código de los servidores **sin ejecutarlo**.

## Qué hay que entregar

1. **Recolección** de 50 a 100 servidores públicos de npm. Ya hecha: `recolectar.py`.
2. **Reglas de Semgrep** para el código, en `reglas/`.
3. **Detectores propios en Python** para lo que Semgrep no cubre bien (`package.json`, dependencias).
4. Un `analizador.py` que junte todo y devuelva hallazgos.

## Cómo se conecta al pipeline

El pipeline llama a `frente_a_estatico.analizador.analizar(dir_servidor)` para cada servidor. La función recibe la carpeta del servidor (con `manifest.json` y `codigo/`) y devuelve una lista de hallazgos creados con `comun.formatos.hallazgo(...)`. Ya está registrada en `ANALIZADORES`, en `frente_c_pipeline/pipeline.py`.

Cada regla de Semgrep declara su categoría en `metadata.categoria`; el `id` de la regla es libre y queda en el campo `regla`. Así puede haber varias reglas para una misma categoría:

```yaml
rules:
  - id: exec-con-plantilla
    metadata:
      categoria: ejecucion-de-comando
    ...
```

Si Semgrep falla, el analizador lanza un error en vez de devolver una lista vacía, y el pipeline lo registra. Así un fallo no se confunde con "no hay hallazgos".

## Estado

Las 7 categorías del frente están implementadas:

| Categoría | Cómo se detecta | Dónde |
| --- | --- | --- |
| `ejecucion-de-comando` | Semgrep: `exec`/`execSync` con comando dinámico, `spawn`/`execFile` con `shell: true`, shells explícitas | `reglas/ejecucion-de-comando.yml` |
| `exfiltracion-red` | Semgrep *taint*: `process.env`, `hostname()`, `userInfo()` o archivos sensibles que llegan a `fetch`, `http(s)`, `axios`, `got`, sockets | `reglas/exfiltracion_red.yaml` |
| `lectura-archivo-sensible` | Semgrep *taint* y rutas construidas hacia `.ssh`, `.aws`, `.npmrc`, `.netrc`, `~/.env`… | `reglas/lectura_archivo_sensible.yaml` |
| `codigo-ofuscado` | Semgrep *taint*: base64, hex, `fromCharCode`… que llegan a `eval`, `new Function`, `vm.*` | `reglas/codigo_ofuscado.yaml` |
| `secreto-hardcodeado` | Python: patrones de alta confianza (AWS, GitHub, Slack, claves privadas…) | `detectores_python.py` |
| `dependencia-typosquat` | Python: distancia de edición contra una lista de paquetes populares | `detectores_python.py` |
| `script-instalacion` | Python: `preinstall`, `install`, `postinstall` (severidad alta si sale a la red o ejecuta código) | `detectores_python.py` |

Resultados (21 de noviembre de 2026):

| Conjunto | Precisión | Recall del frente A | Benignos marcados |
| --- | --- | --- | --- |
| Desarrollo | 1,00 | 9 de 9 | 0 de 6 |
| Validación privada | 1,00 | 8 de 8 | 0 de 3 |

### Para el informe

- `exec-comando-dinamico` tiene severidad **media**: marca cualquier comando armado con variables, lo que es riesgo pero no prueba que el dato venga del modelo. En servidores reales estos hallazgos se revisan a mano y se reportan como *posible* inyección. La inyección **confirmada** la entrega el sandbox (`inyeccion-confirmada`, severidad alta).
- `.env` se considera sensible en el proyecto o directamente en el home (`~/.env`), no dentro de la carpeta de configuración propia de una app (`~/.miapp/.env`), según `docs/categorias.md`.

## Cuidado con los falsos positivos

El banco de pruebas trae benignos que se parecen a los maliciosos, justamente para atrapar reglas demasiado amplias:

| Benigno | Qué regla ingenua lo marcaría |
| --- | --- |
| `benigno-ping-seguro` | Cualquier ejecución de procesos (usa `execFile` con argumentos, sin shell) |
| `benigno-api-clima` | Cualquier `fetch` o uso de `process.env` (los usa de forma legítima) |
| `benigno-notas` | Cualquier lectura o escritura de archivos |
| `benigno-codificar-base64` | Cualquier uso de base64, aunque no ejecute nada |

`tests/test_pipeline.py` falla si una regla marca algún benigno.

## Cómo probarlo solo

```bash
python -m frente_c_pipeline.pipeline corpus/banco_de_pruebas resultados/a.json --analizadores frente_a_estatico.analizador
python -m frente_c_pipeline.evaluar corpus/banco_de_pruebas/ground_truth.json resultados/a.json
python -m pytest -q
```

Mirar la columna `A:analizador` de la matriz de detección y que ningún benigno salga marcado.

## Descargar el corpus real

```bash
python frente_a_estatico/recolectar.py corpus/real --n 100
```

- Solo descarga y descomprime, verificando la integridad del paquete. **Nunca ejecuta `npm install` ni scripts.**
- Elige los servidores al azar con una semilla fija (`--semilla`), para que la muestra sea reproducible y se pueda citar en el informe.
- Si se interrumpe, se puede volver a correr: retoma donde quedó y rehace los paquetes que quedaron a medias.
- Deja fuera los servidores solo remotos, los de PyPI y los paquetes de más de 20 MB (o 200 MB descomprimidos). Hay que decirlo en las limitaciones.

## Notas

- Muchos paquetes de npm traen JavaScript compilado o minificado, no TypeScript (el caso `exfil-minificado` lo imita en `dist/`). Las reglas deben revisar todos los archivos, no solo `src/`, y los hallazgos en código minificado cuestan más de leer.
- Semgrep tarda unos 2 segundos por servidor (arranca una vez por cada uno); 100 servidores toman unos 4 minutos.
- Semgrep funciona en Windows (probado). Instalarlo en el mismo Python o entorno virtual con que se corre el pipeline: `python -m pip install semgrep`.
- Los hallazgos sobre servidores reales se **revisan a mano** antes de afirmar nada, y se anonimizan en el informe.
