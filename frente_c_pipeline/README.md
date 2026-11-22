# Frente C: banco de pruebas, pipeline, evaluación, reporte y sandbox

Une los frentes A y B en una sola herramienta y mide qué tan bien funciona.

## Qué hay aquí

| Archivo | Para qué sirve |
| --- | --- |
| `pipeline.py` | Corre los analizadores sobre un corpus y escribe `hallazgos.json` y `hallazgos.log.json` |
| `evaluar.py` | Precisión, recall y matriz de detección contra el ground truth |
| `reporte.py` | Puntaje de riesgo por servidor, en Markdown y JSON |
| `corrida_informe.py` | Corrida completa para el informe: desarrollo, validación y reales en un paso, con tablas |
| `revision.py` | Resume la revisión manual de los hallazgos reales (precisión estimada) |
| `generar_banco.py` | Regenera el banco de desarrollo, o el de validación con `--conjunto validacion` |
| `validacion_privada.py` | Casos del conjunto de validación. **No está en git**: guardar una copia aparte |
| `tsconfig.banco.json` | Para compilar el banco con `tsc` (lo usa la CI) |
| `sandbox/` | Ejecuta los servidores de prueba en contenedores aislados |

## Pipeline

```bash
# Todo
python -m frente_c_pipeline.pipeline corpus/banco_de_pruebas resultados/hallazgos.json
# Solo algunos módulos
python -m frente_c_pipeline.pipeline corpus/banco_de_pruebas resultados/a.json --analizadores frente_a_estatico.analizador
# Sumando los hallazgos del sandbox
python -m frente_c_pipeline.pipeline corpus/banco_de_pruebas resultados/todo.json --dinamico resultados/dinamico
```

- Importa los módulos de `ANALIZADORES` (arriba de `pipeline.py`) y suma lo que devuelve `analizar()` de cada uno.
- Valida cada hallazgo contra `comun/formatos.py` y le agrega el campo `analizador`.
- Si un analizador falla en un servidor, registra el error y sigue. Los errores, la fecha, el corpus y la duración quedan en `<salida>.log.json`. **Revisarlo**: un frente que falla en todos los servidores aparece como "0 hallazgos".
- No lee el ground truth.

## Evaluación

```bash
python -m frente_c_pipeline.evaluar corpus/banco_de_pruebas/ground_truth.json resultados/todo.json --json resultados/metricas.json
```

Imprime:
- precisión y recall global y por categoría;
- cuántos maliciosos se detectan y cuántos benignos se marcan por error;
- la **matriz de detección**: cada problema esperado del banco, y qué analizador lo encontró. Es la tabla para responder qué detecta cada técnica.

Un acierto es un par (servidor, categoría). `--json` guarda las métricas para el informe.

## Reporte

```bash
python -m frente_c_pipeline.reporte resultados/todo.json resultados/reporte.md --corpus corpus/real --anonimizar
```

Puntaje por servidor = suma del peso de cada categoría distinta encontrada (alta=3, media=2, baja=1). `--corpus` incluye los servidores sin hallazgos y `--anonimizar` reemplaza los nombres por S01, S02... Usar siempre `--anonimizar` con servidores reales en el informe.

## Banco de pruebas

18 servidores escritos por el equipo: 6 benignos (4 de ellos parecidos a los maliciosos) y 12 con un problema conocido. Están descritos en `corpus/banco_de_pruebas/LEEME.md`. Para agregar o cambiar casos, se edita `generar_banco.py` y se regenera:

```bash
python -m frente_c_pipeline.generar_banco corpus/banco_de_pruebas
```

Un test comprueba que el banco versionado coincide con el generador, así que no se edita a mano. Los servidores son inertes: los destinos de red usan el dominio reservado `.invalid`, que nunca resuelve, y las claves son de ejemplo.

## Conjunto de validación (privado)

13 servidores (3 benignos, 10 maliciosos) con variantes que **no están** en el banco de desarrollo, tomadas de las familias de [docs/categorias.md](../docs/categorias.md). Sirven para medir si las reglas de A y B generalizan o solo memorizaron los ejemplos.

- Los casos están en `validacion_privada.py` y se generan en `corpus/validacion/`. **Ninguno de los dos se sube a git** ni se comparte con quienes escriben reglas.
- **Guarda una copia de `validacion_privada.py` fuera del repositorio** (por ejemplo en tu OneDrive): si se pierde, no hay otra.
- Se usa una sola vez, al final, cuando A y B den por terminadas sus reglas:

```bash
python -m frente_c_pipeline.generar_banco corpus/validacion --conjunto validacion
python frente_c_pipeline/sandbox/ejecutar.py corpus/validacion resultados/dinamico_val
python -m frente_c_pipeline.pipeline corpus/validacion resultados/val.json --dinamico resultados/dinamico_val
python -m frente_c_pipeline.evaluar corpus/validacion/ground_truth.json resultados/val.json --json resultados/metricas_val.json
```

En el informe se reportan ambos resultados, desarrollo y validación, lado a lado. Si después de evaluar se corrigen reglas mirando la validación, ese resultado deja de valer como validación: hay que decirlo.

## Sandbox (ejecución aislada)

Requiere Docker. Ejecuta cada servidor de prueba en un contenedor sin red, de solo lectura, sin capacidades y con límites de memoria y procesos. Un cliente MCP lo arranca, lista sus herramientas y las llama dos veces:

1. **Con datos normales.** Si la respuesta ya trae un señuelo (`HONEYTOKEN-...`), el servidor lee archivos sensibles por su cuenta: `lectura-archivo-sensible`.
2. **Con payloads** en cada parámetro de texto: `127.0.0.1; cat ~/.ssh/id_rsa`, `x | cat ~/.ssh/id_rsa` y una ruta con `../` hasta la llave. Si el señuelo aparece **solo** con el payload, la vulnerabilidad queda **confirmada**: `ejecucion-de-comando` (regla `inyeccion-confirmada`) o `lectura-archivo-sensible` (regla `traversal-confirmado`). La imagen trae señuelos en `~/.ssh`, `~/.aws` y variables de entorno, y usa las mismas versiones del SDK y de zod con que se probó el banco.

```bash
python frente_c_pipeline/sandbox/ejecutar.py corpus/banco_de_pruebas resultados/dinamico
```

**Estado:** probado en Windows con Docker Desktop. Los payloads se verificaron fuera de Docker sobre los 31 servidores: confirman la inyección de `vuln-inyeccion-comandos` y la del caso equivalente de validación, y no marcan `benigno-ping-seguro` ni `benigno-notas` (que resisten la inyección y el `../`). La primera corrida descarga la imagen base y tarda un par de minutos. Solo es para el banco de pruebas: el cliente arranca `src/index.ts`, y el alcance comprometido no ejecuta código de terceros.

Limitaciones de esta versión:
- Solo bloquea la red; no registra los intentos de conexión, así que `exfil-variables-entorno` no se detecta de forma dinámica.
- Solo detecta lo que se refleja en la respuesta: una inyección que no devuelve la salida del comando no se confirma.

## Corrida para el informe

Un solo comando corre desarrollo, validación y los servidores reales, y deja todo en `resultados/informe/<fecha_hora>/`:

```bash
python -m frente_c_pipeline.corrida_informe --sandbox
```

- `--sandbox` corre el sandbox (Docker) sobre desarrollo y validación. Sin él, usa los resultados que ya existan en `resultados/dinamico` y `resultados/dinamico_val`, y avisa de qué fecha son.
- `--sin-validacion` y `--sin-reales` saltan esos conjuntos. Los reales nunca pasan por el sandbox.
- Para los 100 reales tarda unos 12 minutos. Los reales tienen que ser la muestra oficial: `python frente_a_estatico/recolectar.py corpus/real --desde-muestra corpus/muestra_real.json`.

| Archivo | Para qué |
| --- | --- |
| `tablas.md` | Tablas listas para el informe: desarrollo frente a validación, qué detecta cada técnica, recall por categoría, matrices y resumen de reales |
| `tabla_resumen.csv`, `tabla_categorias.csv` | Las mismas cifras para hacer gráficos (separadas con `;`, se abren directo en Excel) |
| `resumen.md` | Fecha, versión del código, analizadores, errores y avisos. **Revisarlo siempre** |
| `reporte_real_anonimo.md` | Riesgo por servidor real con nombres S01, S02… Este es el que va al informe |
| `revision_manual.csv` | Hallazgos reales para revisar a mano. **Privado**: tiene nombres reales |
| `mapa_anonimizacion.csv` | S01 → nombre real. **Privado** |

Las tablas de validación son privadas mientras alguien siga escribiendo reglas o heurísticas. Cuando el frente B entregue, se repite la corrida y sus columnas aparecen solas.

## Revisión manual de los hallazgos reales

Sin revisión manual, los hallazgos en servidores reales son sospechas, no vulnerabilidades. Para estimar cuántos son correctos:

1. Abre `revision_manual.csv` en Excel. Para cada hallazgo, mira el código en `corpus/real/<servidor>/<ubicacion>` y escribe en **veredicto**:
   - `verdadero`: el problema existe (por ejemplo, un parámetro de una herramienta llega de verdad a `exec`).
   - `falso`: no es un problema (por ejemplo, el comando es fijo o lo arma el propio autor).
   - `dudoso`: no se puede decidir leyendo el código.
   En **nota**, una frase con el porqué.
2. Guarda el archivo (como CSV) y corre:
   ```bash
   python -m frente_c_pipeline.revision resultados/informe/<fecha_hora>/revision_manual.csv
   ```
   Imprime la precisión estimada en servidores reales, global, por categoría y por regla, y la guarda en `revision_resumen.md`.

Es la respuesta a la pregunta de investigación 1 y la cifra que más valida el trabajo. Si algún hallazgo es un problema real y grave, se aplica el protocolo de la sección de ética del README principal antes de mencionarlo.

## Pendiente

1. Repetir la corrida para el informe cuando el frente B entregue.
2. Revisar a mano los hallazgos reales (sección anterior).
3. Observar la red del contenedor (trabajo futuro).
