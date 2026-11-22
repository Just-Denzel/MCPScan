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

El registry de MCP cambia con el tiempo: la misma semilla, en otra fecha, sortea otra muestra (entre el 9 y el 22 de noviembre solo coincidían 33 de 100 servidores). Por eso la muestra oficial del proyecto está guardada en **`corpus/muestra_real.json`** (paquete, versión e integridad de cada servidor), y todos descargan exactamente esa:

```bash
python frente_a_estatico/recolectar.py corpus/real --desde-muestra corpus/muestra_real.json
```

Tarda menos de un minuto. Verifica que cada paquete sea idéntico al de la muestra (por su hash de integridad), y avisa si en `corpus/real` hay servidores que no están en ella.

Otras formas de uso:

```bash
# Sortear una muestra nueva del registry de hoy (NO usar para el informe: cambia los resultados)
python frente_a_estatico/recolectar.py corpus/real --n 100 --semilla 1

# Guardar la lista exacta de un corpus ya descargado
python frente_a_estatico/recolectar.py corpus/real --exportar-muestra corpus/muestra_real.json
```

- Solo descarga y descomprime. **Nunca ejecuta `npm install` ni scripts.**
- Si se interrumpe, se puede volver a correr: no repite lo ya descargado y rehace lo que quedó a medias.
- Deja fuera los servidores solo remotos, los de PyPI y los paquetes de más de 20 MB (o 200 MB descomprimidos). Hay que decirlo en las limitaciones.

## Notas

- Muchos paquetes de npm traen JavaScript compilado o minificado, no TypeScript (el caso `exfil-minificado` lo imita en `dist/`). Las reglas deben revisar todos los archivos, no solo `src/`, y los hallazgos en código minificado cuestan más de leer.
- Semgrep corre con límites explícitos (archivos de hasta 10 MB y 120 s por regla, en `analizador.py`). Con los valores por defecto (1 MB y 5 s) se perdían hallazgos en archivos compilados grandes sin avisar, y el resultado cambiaba según la máquina. Si aun así no puede analizar un archivo completo, el pipeline muestra `ATENCIÓN … puede faltar algún hallazgo`.
- Con esos límites, los 100 servidores reales toman unos 11 minutos.
- Semgrep funciona en Windows (probado). Instalarlo en el mismo Python o entorno virtual con que se corre el pipeline: `python -m pip install semgrep`.
- Los hallazgos sobre servidores reales se **revisan a mano** antes de afirmar nada, y se anonimizan en el informe.
