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

## Qué falta

| Categoría | Cómo detectarla | Estado |
| --- | --- | --- |
| `ejecucion-de-comando` | Regla Semgrep | Hecha (versión simple) |
| `exfiltracion-red` | Semgrep: `fetch(...)` o `http.request(...)` con `process.env` completo o datos del usuario | Falta |
| `lectura-archivo-sensible` | Semgrep: `fs.readFileSync` sobre rutas con `.ssh`, `.aws`, `.env` | Falta |
| `secreto-hardcodeado` | gitleaks, o reglas de Semgrep para secretos | Falta |
| `dependencia-typosquat` | Python: comparar nombres de `package.json` con los paquetes populares de npm | Falta |
| `script-instalacion` | Python: leer `scripts` de `package.json` | Falta |

La regla de `ejecucion-de-comando` es simple a propósito. Una mejora importante es pasarla a modo **taint**, que sigue un valor desde el parámetro de una herramienta MCP hasta `exec`. Eso la hace específica de MCP.

## Cuidado con los falsos positivos

El banco de pruebas trae benignos que se parecen a los maliciosos, justamente para atrapar reglas demasiado amplias:

| Benigno | Qué regla ingenua lo marcaría |
| --- | --- |
| `benigno-ping-seguro` | Cualquier ejecución de procesos (usa `execFile` con argumentos, sin shell) |
| `benigno-api-clima` | Cualquier `fetch` o uso de `process.env` (los usa de forma legítima) |
| `benigno-notas` | Cualquier lectura o escritura de archivos |

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

- Muchos paquetes de npm traen JavaScript compilado o minificado, no TypeScript. Las reglas sirven para ambos, pero los hallazgos pueden costar más de leer.
- Semgrep tarda unos 2 segundos por servidor (arranca una vez por cada uno); 100 servidores toman unos 4 minutos.
- Semgrep funciona en Windows (probado). Instalarlo en el mismo Python o entorno virtual con que se corre el pipeline: `python -m pip install semgrep`.
- Los hallazgos sobre servidores reales se **revisan a mano** antes de afirmar nada, y se anonimizan en el informe.
