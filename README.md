# MCPScan

Herramienta que analiza servidores MCP públicos y entrega un reporte de riesgo por servidor, **sin ejecutar código de terceros**. Busca dos tipos de problema:

- **Código del servidor** (frente A): ejecución de comandos con datos del modelo, lectura de archivos sensibles, envío de datos a dominios externos, secretos hardcodeados, dependencias sospechosas y scripts de instalación.
- **Descripciones de las herramientas** (frente B): *tool poisoning*, es decir, instrucciones ocultas dirigidas al modelo dentro del texto que describe una herramienta.

Proyecto final del curso de Seguridad Computacional (PUC Chile, 2026-2).

**Integrantes:** Mario Rojas, Mauricio Pino, Fernando García.

## Arquitectura

Tres partes que forman una sola herramienta y se conectan solo por el contrato de `comun/formatos.py` (explicado en [docs/formatos.md](docs/formatos.md)).

```
                          corpus/  (una carpeta por servidor)
                             │
          ┌──────────────────┴──────────────────┐
          ▼                                     ▼
 frente_a_estatico                    frente_b_descripciones
 analiza codigo/                      analiza herramientas.json
          │                                     │
          └──────────────► hallazgos ◄──────────┘
                              │          ▲
                              │          └── frente_c_pipeline/sandbox (hallazgos dinámicos)
                              ▼
          frente_c_pipeline: pipeline → evaluar (precisión, recall, matriz)
                                      → reporte (riesgo por servidor)
```

## Estructura de carpetas

```
MCPScan/
├── README.md
├── requirements.txt             Python 3.12+: semgrep y pytest
├── comun/
│   └── formatos.py              Contrato: categorías, severidades, hallazgo() y validar()
├── docs/
│   ├── formatos.md              El contrato explicado
│   └── categorias.md            Qué cuenta en cada categoría y sus variantes
├── corpus/
│   ├── banco_de_pruebas/        18 servidores propios + ground_truth.json (desarrollo, versionado)
│   ├── validacion/              conjunto de validación privado (NO se sube a git)
│   ├── muestra_real.json        lista exacta de los 100 servidores reales analizados
│   ├── muestra_control.json     67 servidores reales para validar mejoras de reglas
│   └── real/                    servidores públicos descargados (NO se sube a git)
├── frente_a_estatico/           Análisis estático del código
│   ├── analizador.py            analizar(dir_servidor) -> hallazgos
│   ├── recolectar.py            descarga N servidores de npm al corpus
│   └── reglas/                  reglas de Semgrep
├── frente_b_descripciones/      Tool poisoning
│   ├── heuristicas.py           analizar(dir_servidor) -> hallazgos (técnica 1)
│   ├── clasificador_llm.py      analizar(dir_servidor) -> hallazgos (técnica 2, LLM-as-judge)
│   ├── extractor.py             reconstruye herramientas.json desde el código de los reales
│   ├── comparar.py              compara las dos técnicas (métricas, costo, consistencia)
│   └── prompts/                 prompts del clasificador LLM
├── frente_c_pipeline/           Pipeline, evaluación, reporte y ejecución aislada
│   ├── pipeline.py              corre los analizadores y escribe hallazgos.json
│   ├── evaluar.py               compara con el ground truth
│   ├── reporte.py               puntaje de riesgo por servidor
│   ├── corrida_informe.py       corrida completa con tablas para el informe
│   ├── revision.py              resume la revisión manual de hallazgos reales
│   ├── generar_banco.py         regenera el banco de pruebas
│   └── sandbox/                 Dockerfile, cliente MCP y ejecutor
├── tests/                       pytest: contrato, banco de pruebas, pipeline
├── .github/workflows/ci.yml     corre los tests y compila el banco en cada push
└── resultados/                  salidas de las corridas (NO se suben a git)
```

Cada frente tiene su propio README con su diseño, cómo correrlo y sus resultados.

## Desarrollo y validación

Hay dos conjuntos de servidores de prueba, con respuestas conocidas:

- **Desarrollo** (`corpus/banco_de_pruebas`, 18 servidores): se usó para escribir y ajustar las reglas y heurísticas.
- **Validación** (`corpus/validacion`, 13 servidores): variantes nuevas de las mismas familias de ataque, que no se vieron al escribir las reglas. No está en el repositorio, para que siga siendo un conjunto ciego.

Las reglas se escribieron contra la especificación de [docs/categorias.md](docs/categorias.md), no contra los ejemplos del banco. Si la validación diera mucho peor que el desarrollo, las reglas habrían memorizado los ejemplos en vez de generalizar.

## Cómo agregar un analizador

Un analizador es un módulo de Python con una función que devuelve hallazgos, construidos con `hallazgo()` de `comun/formatos.py`:

```python
from comun.formatos import hallazgo

def analizar(dir_servidor: Path) -> list[dict]:
    return [hallazgo(servidor=dir_servidor.name, categoria="ejecucion-de-comando",
                     regla="mi-regla", severidad="alta", evidencia="...", ubicacion="codigo/a.js:10")]
```

1. Escribir `analizar()` en un módulo nuevo.
2. Agregar el módulo a `ANALIZADORES`, en `frente_c_pipeline/pipeline.py`.
3. Probarlo contra el banco de pruebas y mirar su columna en la matriz de detección.

`hallazgo()` rechaza categorías o severidades que no existen, así que un error de tipeo se ve de inmediato. Si un analizador falla en un servidor, el pipeline lo registra y sigue con el resto.

## Cómo correr

Desde la raíz del repositorio:

```bash
pip install -r requirements.txt

# Pipeline completo sobre el banco de pruebas
# (el clasificador LLM del frente B necesita GEMINI_API_KEY en un archivo .env; ver frente_b_descripciones/README.md)
python -m frente_c_pipeline.pipeline corpus/banco_de_pruebas resultados/hallazgos.json

# Comparación de las técnicas del frente B (heurísticas frente a LLM)
python -m frente_b_descripciones.comparar corpus/banco_de_pruebas --repeticiones 3

# Solo un módulo
python -m frente_c_pipeline.pipeline corpus/banco_de_pruebas resultados/a.json --analizadores frente_a_estatico.analizador

# Precisión, recall y matriz de detección
python -m frente_c_pipeline.evaluar corpus/banco_de_pruebas/ground_truth.json resultados/hallazgos.json

# Reporte de riesgo por servidor (anonimizado, para el informe)
python -m frente_c_pipeline.reporte resultados/hallazgos.json resultados/reporte.md --corpus corpus/banco_de_pruebas --anonimizar

# Todo de una vez para el informe (desarrollo, validación, reales y tablas)
python -m frente_c_pipeline.corrida_informe --sandbox

# Tests
python -m pytest -q
```

Notas para Windows:
- Semgrep funciona en Windows (probado). Tiene que estar instalado en el **mismo Python o entorno virtual** con que se corre el pipeline; si no, el pipeline avisa con `ATENCIÓN`.
- Docker Desktop es necesario solo para el sandbox.
- Si `python` no funciona, probar con `py`.

## Seguridad y ética

- El análisis es estático: **no se ejecuta código de terceros.** Los paquetes se descargan y descomprimen, nunca se instalan ni se corren sus scripts. El sandbox solo ejecuta los servidores propios del banco de pruebas.
- Los servidores del banco de pruebas son propios y están diseñados para ser inertes (dominios `.invalid`, claves de ejemplo). No se publican como paquetes.
- Las vulnerabilidades encontradas en servidores reales se informan a sus autores y al equipo docente **antes** de cualquier divulgación.
- Los servidores reales se nombran de forma anónima (S01, S02…, con `reporte.py --anonimizar`), y no se publican secretos ni datos sensibles encontrados.
- Las claves de API van en un archivo `.env` o en variables de entorno, nunca en el repositorio (`.env` está en `.gitignore`).
- La CI de GitHub corre los tests y compila el banco de pruebas en cada push.

## Resultados

Corrida final del 23 de noviembre de 2026 (versión `6f6a617`, Semgrep 1.184.0), con el análisis estático, las heurísticas, el clasificador LLM y el sandbox:

| Conjunto | Servidores | Precisión | Recall | Maliciosos detectados | Benignos marcados |
| --- | --- | --- | --- | --- | --- |
| Desarrollo | 18 | 0,93 | 1,00 (14 de 14 problemas) | 12 de 12 | 0 de 6 |
| Validación | 13 | 1,00 | 1,00 (12 de 12 problemas) | 10 de 10 | 0 de 3 |

Aciertos y falsos positivos de cada técnica (un acierto es un par servidor y categoría):

| Técnica | Desarrollo | Validación |
| --- | --- | --- |
| A: análisis estático | 9 aciertos, 0 falsos positivos | 8 aciertos, 0 falsos positivos |
| B: heurísticas | 5, 0 | 4, 0 |
| B: clasificador LLM | 4, 1 | 3, 0 |
| Sandbox | 2, 0 | 1, 0 |

El único falso positivo es del clasificador LLM: detectó el servidor `poison-parafraseado`, pero lo clasificó como instrucción explícita en vez de parafraseada. Sin el LLM, la precisión en desarrollo es 1,00.

En los **100 servidores reales** (muestra de `corpus/muestra_real.json`), el análisis estático marca **7 problemas distintos** (servidor y categoría) en 7 servidores. La revisión manual confirmó 2 (precisión 0,29): un script `postinstall` (S07) y **una vulnerabilidad real**, una inyección de comandos en la que los argumentos que envía el modelo llegan sin validar a una shell (S01), informada a su mantenedor. Contados como hallazgos sueltos son 27, pero 10 repiten en el código compilado (`dist/`) puntos del código fuente de S01; sin duplicados son 17, de los cuales 11 son verdaderos. Las dos técnicas del frente B no marcan ninguno de los 88 servidores cuyas herramientas se pudieron extraer.

Detalle de cada parte: [frente A](frente_a_estatico/README.md), [frente B](frente_b_descripciones/README.md), [frente C](frente_c_pipeline/README.md).

## Limitaciones

- Solo servidores de npm, con código JavaScript o TypeScript; quedan fuera los servidores solo remotos, los de PyPI y los paquetes muy grandes.
- La regla específica de MCP sigue el dato dentro de un mismo archivo. En algunos archivos minificados grandes Semgrep no logra un análisis completo y lo avisa.
- Los hallazgos de severidad media en servidores reales requieren revisión manual.
- El banco tiene pocos casos por categoría y no hay tool poisoning en la muestra real, así que el recall del frente B fuera del banco no se pudo medir.
- El sandbox solo confirma lo que se refleja en la respuesta y no registra intentos de conexión a la red.
