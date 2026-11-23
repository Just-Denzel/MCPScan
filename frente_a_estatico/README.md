# Frente A: análisis estático del código

Detecta patrones peligrosos en el código de los servidores **sin ejecutarlo**.

## Qué hay en esta carpeta

| Archivo | Qué hace |
| --- | --- |
| `recolectar.py` | Descarga servidores públicos de npm al corpus, sin instalarlos ni ejecutarlos |
| `reglas/` | Reglas de Semgrep para el código JavaScript y TypeScript |
| `detectores_python.py` | Detectores para lo que Semgrep no cubre bien (`package.json`, dependencias, secretos) |
| `analizador.py` | Junta las dos cosas y devuelve hallazgos (`analizar()` para el pipeline) |

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

## Categorías

Las 7 categorías del frente:

| Categoría | Cómo se detecta | Dónde |
| --- | --- | --- |
| `ejecucion-de-comando` | **Alta:** Semgrep *taint* específico de MCP: un argumento de una herramienta (`server.tool`, `registerTool`, `request.params`) llega a una shell, directo o vía una función envoltorio. **Media:** cualquier comando armado con variables, `shell: true` o shells explícitas, de origen desconocido | `reglas/mcp_argumento_a_shell.yaml`, `reglas/ejecucion-de-comando.yml` |
| `exfiltracion-red` | Semgrep *taint*: `process.env`, `hostname()`, `userInfo()` o archivos sensibles que llegan a `fetch`, `http(s)`, `axios`, `got`, sockets | `reglas/exfiltracion_red.yaml` |
| `lectura-archivo-sensible` | Semgrep *taint* hacia funciones que leen archivos, y rutas armadas con `path.join` o desde `homedir()` hacia `.ssh`, `.aws`, `.npmrc`, `.netrc`, `~/.env`… | `reglas/lectura_archivo_sensible.yaml` |
| `codigo-ofuscado` | Semgrep *taint*: base64, hex, `fromCharCode`… que llegan a `eval`, `new Function`, `vm.*` | `reglas/codigo_ofuscado.yaml` |
| `secreto-hardcodeado` | Python: patrones de alta confianza (AWS, GitHub, Slack, claves privadas…); ignora claves recortadas de ejemplo (`…`) | `detectores_python.py` |
| `dependencia-typosquat` | Python: distancia de edición contra una lista de paquetes populares | `detectores_python.py` |
| `script-instalacion` | Python: `preinstall`, `install`, `postinstall` (severidad alta si sale a la red o ejecuta código) | `detectores_python.py` |

Resultados (corrida final del 23 de noviembre de 2026):

| Conjunto | Precisión | Recall del frente A | Benignos marcados |
| --- | --- | --- | --- |
| Desarrollo | 1,00 | 9 de 9 | 0 de 6 |
| Validación | 1,00 | 8 de 8 | 0 de 3 |

### Severidad

- **Alta** en `ejecucion-de-comando` solo con la regla específica de MCP (`mcp-argumento-a-shell`): está comprobado en el código que un argumento del modelo llega a la shell.
- **Media** para los comandos armados con variables de origen desconocido (`exec-comando-dinamico`, `spawn-con-shell`, `shell-explicita-dinamica`). Son riesgo, pero no prueban que el dato venga del modelo: en servidores reales se revisan a mano.
- `.env` cuenta como sensible solo en el home (`~/.env`). El `.env` de un proyecto o del propio servidor es configuración normal.
- Las rutas sensibles cuentan si se arman como ruta (`path.join`, desde `homedir()`) o llegan a una lectura; un texto que solo las menciona (documentación, descripciones) no cuenta.

### Mejora con servidores reales (22 de noviembre de 2026)

La primera versión de las reglas tuvo precisión 1,00 en el banco, pero en la revisión manual de 100 servidores reales sus 9 hallazgos de severidad alta fueron falsos positivos, y la única inyección real estaba marcada como media. Se ajustaron las reglas mirando esos casos (que pasan a ser datos de desarrollo) y se midió en una **muestra de control** de 67 servidores que no se usó para ajustarlas (`corpus/muestra_control.json`):

| Muestra | Versión | Alta: hallazgos (verdaderos) | Media: hallazgos (verdaderos) |
| --- | --- | --- | --- |
| Desarrollo (100 reales) | antes | 9 (0) | 7 (3) |
| Desarrollo (100 reales) | después | 9 (9), todos de la misma vulnerabilidad | 9 (3) |
| Control (67 reales) | antes | 1 (0) | 15 (2) |
| Control (67 reales) | después | 0 | 16 (2) |

**Nota sobre la corrida final (23 de noviembre de 2026):** ahí la severidad alta registra **18 hallazgos, no 9**. Son los mismos 9 de `src/index.ts`, repetidos en el código compilado (`dist/index.js`) que trae el mismo paquete: el analizador revisa los dos archivos. Todos corresponden a una sola vulnerabilidad en un solo servidor (S01). La tabla de arriba cuenta 9, sin duplicados. En el informe se cuenta por problema distinto (servidor y categoría), lo que evita este doble conteo.

El banco de desarrollo y la validación siguen en 9 de 9 y 8 de 8 sin falsos positivos. Límite: la muestra de control no tiene ninguna inyección real, así que en ella se midió que la severidad alta no da falsas alarmas, no su capacidad de encontrar inyecciones reales. La validación se usó para comprobar que no se rompiera nada, así que su resultado ya no es del todo ciego para esta versión.

Los casos de `tests/casos_reglas/` documentan qué debe y qué no debe detectar cada regla; `tests/test_reglas.py` los comprueba.

## Benignos parecidos a los maliciosos

El banco de pruebas trae benignos que se parecen a los maliciosos, para detectar reglas demasiado amplias:

| Benigno | Qué regla ingenua lo marcaría |
| --- | --- |
| `benigno-ping-seguro` | Cualquier ejecución de procesos (usa `execFile` con argumentos, sin shell) |
| `benigno-api-clima` | Cualquier `fetch` o uso de `process.env` (los usa de forma legítima) |
| `benigno-notas` | Cualquier lectura o escritura de archivos |
| `benigno-codificar-base64` | Cualquier uso de base64, aunque no ejecute nada |

`tests/test_pipeline.py` falla si una regla marca algún benigno.

## Cómo correrlo

```bash
python -m frente_c_pipeline.pipeline corpus/banco_de_pruebas resultados/a.json --analizadores frente_a_estatico.analizador
python -m frente_c_pipeline.evaluar corpus/banco_de_pruebas/ground_truth.json resultados/a.json
python -m pytest -q
```

La columna `A:analizador` de la matriz de detección muestra qué encuentra este frente.

## Descargar el corpus real

El registry de MCP cambia con el tiempo: la misma semilla, en otra fecha, sortea otra muestra (entre el 9 y el 22 de noviembre solo coincidían 33 de 100 servidores). Por eso la muestra oficial del proyecto está guardada en **`corpus/muestra_real.json`** (paquete, versión e integridad de cada servidor), y se descarga exactamente esa:

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
- Deja fuera los servidores solo remotos, los de PyPI y los paquetes de más de 20 MB (o 200 MB descomprimidos).

## Notas

- Muchos paquetes de npm traen JavaScript compilado o minificado, no TypeScript (el caso `exfil-minificado` lo imita en `dist/`). Por eso las reglas revisan todos los archivos, no solo `src/`; los hallazgos en código minificado cuestan más de leer.
- Semgrep corre con límites explícitos (archivos de hasta 10 MB y 120 s por regla, en `analizador.py`). Con los valores por defecto (1 MB y 5 s) se perdían hallazgos en archivos compilados grandes sin avisar, y el resultado cambiaba según la máquina. Si aun así no puede analizar un archivo completo, el pipeline muestra `ATENCIÓN … puede faltar algún hallazgo`.
- Con esos límites, los 100 servidores reales toman unos 11 minutos.
- Semgrep funciona en Windows (probado). Instalarlo en el mismo Python o entorno virtual con que se corre el pipeline: `python -m pip install semgrep`.
- Los hallazgos sobre servidores reales se revisaron a mano antes de afirmar nada, y se anonimizan en el informe. En la corrida final, 6 de los 100 servidores tienen un archivo que Semgrep no pudo analizar completo (`PartialParsing`).
