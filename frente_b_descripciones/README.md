# Frente B: tool poisoning en las descripciones

Detecta instrucciones ocultas dirigidas al modelo dentro del texto que describe cada herramienta. El modelo lee esa descripción; el usuario normalmente no.

## Qué hay que entregar

1. **Heurísticas** para las señales conocidas.
2. Un **clasificador basado en LLM** (LLM-as-judge), con su prompt en `prompts/`.
3. Una **comparación** entre ambos: qué detecta cada uno y qué se les escapa.
4. Un **extractor de descripciones** para los servidores reales (ver abajo).

## Cómo se conecta al pipeline

Qué cuenta en cada categoría y en qué variantes puede aparecer está en **[docs/categorias.md](../docs/categorias.md)**. Escriban las heurísticas y el prompt contra esa especificación: al final se evalúan también contra un conjunto de validación con variantes que no están en el banco.

El pipeline llama a `analizar(dir_servidor)` de cada módulo registrado en `ANALIZADORES` (`frente_c_pipeline/pipeline.py`). La función lee `<servidor>/herramientas.json` y devuelve hallazgos creados con `comun.formatos.hallazgo(...)`, con una de estas categorías: `tool-poisoning-instruccion`, `tool-poisoning-unicode`, `tool-poisoning-parafraseado`.

**Para poder comparar las técnicas, cada una debe ser su propio módulo**, por ejemplo:

```
frente_b_descripciones/
  heuristicas.py          analizar() con las heurísticas
  clasificador_llm.py     analizar() con el LLM
```

Se registran los dos en `ANALIZADORES`, y la matriz de detección de `evaluar.py` muestra una columna por cada uno (`B:heuristicas`, `B:clasificador`). Esa matriz es la respuesta directa a la pregunta "qué detecta cada técnica". El `analizador.py` actual es solo un placeholder y se puede borrar cuando existan los otros dos.

## Señales para las heurísticas

- Etiquetas tipo `<IMPORTANT>`, o frases como "no menciones esto al usuario" o "ignora las instrucciones anteriores".
- Caracteres Unicode invisibles: el bloque *tags* (U+E0000 a U+E007F) y los de ancho cero (U+200B, U+200C, U+200D, U+2060).
- Rutas o archivos sensibles: `~/.ssh`, `.env`, `id_rsa`, `credentials`.
- Referencias a otras herramientas, incluso de **otros servidores** (*tool shadowing*).
- Instrucciones escondidas después de muchas líneas en blanco.
- **Las descripciones de los parámetros** (`esquema.properties.*.description`), no solo la de la herramienta.
- Parámetros sin relación con la función de la herramienta (por ejemplo, `contexto` en una suma).

Cuidado: `benigno-busqueda-proyecto` tiene una descripción benigna que dice "Importante", "claves SSH" y "credenciales". Una heurística que solo busque palabras clave la marcará.

## Clasificador LLM

- El borrador del prompt está en `prompts/clasificador_v1.md`.
- Presentar la descripción como **dato**, no como instrucción: es texto escrito por un posible atacante y puede intentar manipular al propio clasificador.
- Pedir la respuesta en JSON, con temperatura baja, y repetir cada análisis varias veces para medir la **consistencia**.
- Anotar el costo por servidor.
- La clave de API va en una variable de entorno, **nunca en el repositorio**.

## Casos del banco de pruebas

| Servidor | Qué debería pasar |
| --- | --- |
| `poison-instruccion-oculta` | Lo detectan las heurísticas y el LLM |
| `poison-unicode-invisible` | Lo detectan las heurísticas; el LLM puede no ver los caracteres invisibles |
| `poison-parafraseado` | Lo detecta el LLM; las heurísticas probablemente no |
| `poison-parametro` | Solo si se revisan las descripciones de los parámetros |
| `poison-otra-herramienta` | Lo detectan las heurísticas (referencia a otra herramienta) y el LLM |
| `benigno-busqueda-proyecto` | No se marca, aunque tiene palabras sospechosas |
| demás `benigno-*` | No se marcan |

Son hipótesis para medir, no resultados.

## Probarlo solo

```bash
python -m frente_c_pipeline.pipeline corpus/banco_de_pruebas resultados/b.json --analizadores frente_b_descripciones.heuristicas frente_b_descripciones.clasificador_llm
python -m frente_c_pipeline.evaluar corpus/banco_de_pruebas/ground_truth.json resultados/b.json
```

## Pendiente importante: descripciones de los servidores reales

Los servidores descargados de npm **no traen `herramientas.json`**, y sin él este frente no puede medir nada en servidores reales (pregunta de investigación 2). El alcance comprometido no ejecuta código de terceros, así que la opción recomendada es **extraer las descripciones leyendo el código**.

Se midió sobre una muestra de 100 servidores reales: en **78** aparece al menos uno de estos patrones, de los que se puede sacar el nombre y la descripción de cada herramienta:

| Patrón en el código | Servidores |
| --- | --- |
| `{ name: "...", description: ... }` (lista de herramientas) | 36 |
| `registerTool("...", ...)` | 25 |
| `server.tool("...", ...)` | 18 |

Es una cota superior aproximada: que el patrón aparezca no garantiza que la extracción salga limpia (texto minificado, descripciones armadas con variables). El extractor escribiría `herramientas.json` en cada carpeta del corpus real, y en el informe se reporta qué porcentaje se pudo extraer.
