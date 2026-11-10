# Frente C: banco de pruebas, pipeline, evaluación, reporte y sandbox

Une los frentes A y B en una sola herramienta y mide qué tan bien funciona.

## Qué hay aquí

| Archivo | Para qué sirve |
| --- | --- |
| `pipeline.py` | Corre los analizadores sobre un corpus y escribe `hallazgos.json` y `hallazgos.log.json` |
| `evaluar.py` | Precisión, recall y matriz de detección contra el ground truth |
| `reporte.py` | Puntaje de riesgo por servidor, en Markdown y JSON |
| `generar_banco.py` | Regenera el banco de pruebas (`corpus/banco_de_pruebas`) |
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

13 servidores escritos por el equipo: 5 benignos (3 de ellos parecidos a los maliciosos) y 8 con un problema conocido. Están descritos en `corpus/banco_de_pruebas/LEEME.md`. Para agregar o cambiar casos, se edita `generar_banco.py` y se regenera:

```bash
python -m frente_c_pipeline.generar_banco corpus/banco_de_pruebas
```

Un test comprueba que el banco versionado coincide con el generador, así que no se edita a mano. Los servidores son inertes: los destinos de red usan el dominio reservado `.invalid`, que nunca resuelve, y las claves son de ejemplo.

## Sandbox (ejecución aislada)

Requiere Docker. Ejecuta cada servidor de prueba en un contenedor sin red, de solo lectura, sin capacidades y con límites de memoria y procesos. Un cliente MCP lo arranca, lista y llama sus herramientas, y marca como hallazgo cualquier señuelo (`HONEYTOKEN-...`) que aparezca en una respuesta. La imagen trae señuelos en `~/.ssh`, `~/.aws` y variables de entorno, y usa las mismas versiones del SDK y de zod con que se probó el banco.

```bash
python frente_c_pipeline/sandbox/ejecutar.py corpus/banco_de_pruebas resultados/dinamico
```

**Estado:** probado en Windows con Docker Desktop sobre los 13 servidores: detecta `lectura-archivos-sensibles` y no marca ningún benigno. La primera corrida descarga la imagen base y tarda un par de minutos. Solo es para el banco de pruebas: el cliente arranca `src/index.ts`, y el alcance comprometido no ejecuta código de terceros.

Limitaciones de esta versión:
- Solo bloquea la red; no registra los intentos de conexión, así que `exfil-variables-entorno` no se detecta de forma dinámica.
- Llama a las herramientas con datos de ejemplo; no prueba payloads de inyección.

## Pendiente

1. Confirmar el aislamiento y guardar la salida como evidencia para el informe:
   ```
   docker run --rm --network none --entrypoint node mcpscan-sandbox -e "fetch('https://example.com').then(()=>console.log('RED ABIERTA: MAL')).catch(()=>console.log('sin red: OK'))"
   docker run --rm --read-only --entrypoint sh mcpscan-sandbox -c "touch /home/sandbox/x && echo 'SE PUDO ESCRIBIR: MAL' || echo 'solo lectura: OK'"
   ```
2. Observar la red del contenedor (por ejemplo con una red Docker interna que registre las conexiones).
3. Cuando A y B entreguen, correr el pipeline sobre `corpus/real` y revisar a mano una muestra de hallazgos para estimar falsos positivos.
4. Tablas y gráficos para el informe a partir de `metricas.json` y `reporte.json`.
