# MCPScan

Herramienta que analiza servidores MCP públicos y entrega un reporte de riesgo por servidor, **sin ejecutar código de terceros**. Busca dos tipos de problema:

- **Código del servidor** (frente A): ejecución de comandos con datos del modelo, lectura de archivos sensibles, envío de datos a dominios externos, secretos hardcodeados, dependencias sospechosas y scripts de instalación.
- **Descripciones de las herramientas** (frente B): *tool poisoning*, es decir, instrucciones ocultas dirigidas al modelo dentro del texto que describe una herramienta.

Proyecto final del curso de seguridad (PUC Chile, 2026-2). Entrega del informe y el código: 19 de noviembre de 2026.

**Integrantes:** Mario Rojas, Mauricio Pino, Fernando García.

## Cómo encaja todo

Tres partes que se desarrollan en paralelo y terminan siendo una sola herramienta. Se conectan solo por el contrato de `comun/formatos.py` (explicado en [docs/formatos.md](docs/formatos.md)).

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
│   ├── formatos.md              El contrato explicado (leer primero)
│   └── categorias.md            Qué cuenta en cada categoría y sus variantes
├── corpus/
│   ├── banco_de_pruebas/        18 servidores propios + ground_truth.json (desarrollo, versionado)
│   ├── validacion/              conjunto de validación privado (NO se sube a git)
│   ├── muestra_real.json        lista exacta de los 100 servidores reales analizados
│   └── real/                    servidores públicos descargados (NO se sube a git)
├── frente_a_estatico/           Análisis estático del código
│   ├── analizador.py            analizar(dir_servidor) -> hallazgos
│   ├── recolectar.py            descarga N servidores de npm al corpus
│   └── reglas/                  reglas de Semgrep
├── frente_b_descripciones/      Tool poisoning
│   ├── analizador.py            analizar(dir_servidor) -> hallazgos
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

Cada frente tiene su propio README con qué entregar, qué falta y cómo probarlo.

## Desarrollo y validación

Hay dos conjuntos de servidores de prueba:

- **Desarrollo** (`corpus/banco_de_pruebas`): todos lo ven y lo usan mientras escriben reglas y heurísticas.
- **Validación** (`corpus/validacion`): variantes nuevas que **solo tiene el frente C** y que no se suben a git. Se evalúa una vez, al final.

Las reglas se escriben contra la especificación de [docs/categorias.md](docs/categorias.md), no contra los ejemplos del banco. En el informe se reportan los dos resultados: si la validación da mucho peor que el desarrollo, las reglas memorizaron los ejemplos en vez de generalizar.

## Cómo conectar cada parte al pipeline

Un analizador es un módulo de Python con una función que devuelve hallazgos, construidos con `hallazgo()` de `comun/formatos.py`:

```python
from comun.formatos import hallazgo

def analizar(dir_servidor: Path) -> list[dict]:
    return [hallazgo(servidor=dir_servidor.name, categoria="ejecucion-de-comando",
                     regla="mi-regla", severidad="alta", evidencia="...", ubicacion="codigo/a.js:10")]
```

1. Escribir `analizar()` en un módulo del frente (ya hay un esqueleto en A y B).
2. Agregar el módulo a `ANALIZADORES`, en `frente_c_pipeline/pipeline.py`.
3. Probarlo solo contra el banco de pruebas y mirar su fila en la matriz de detección.

`hallazgo()` rechaza categorías o severidades que no existen, así que un error de tipeo se ve de inmediato. Si un analizador falla en un servidor, el pipeline lo registra y sigue con el resto.

## Cómo correr

Desde la raíz del repositorio:

```bash
pip install -r requirements.txt

# Pipeline completo sobre el banco de pruebas
python -m frente_c_pipeline.pipeline corpus/banco_de_pruebas resultados/hallazgos.json

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

## Flujo de trabajo en git

- Una rama por frente: `frente-a`, `frente-b`, `frente-c`. Se une a `main` con un pull request, cuando los tests pasan y otra persona lo revisó.
- Cada uno edita **solo su carpeta**. `comun/formatos.py` es de todos: cambiarlo se avisa antes.
- La CI de GitHub corre los tests y compila el banco de pruebas en cada push. Si falla, no se une.
- Nunca subir claves de API: van en variables de entorno o en `.env`, que está en `.gitignore`.

## Seguridad y ética

- El análisis es estático: **no se ejecuta código de terceros.** Los paquetes se descargan y descomprimen, nunca se instalan ni se corren sus scripts.
- Los servidores del banco de pruebas son nuestros y están diseñados para ser inertes (dominios `.invalid`, claves de ejemplo). No se publican como paquetes.
- Si aparece código realmente malicioso o una vulnerabilidad grave en un servidor real: avisar a sus autores, a la plataforma (GitHub o npm) y al equipo docente **antes** de divulgar nada.
- En el informe y la presentación se anonimizan los servidores reales (`reporte.py --anonimizar`) y no se incluyen secretos ni datos sensibles encontrados.

## Estado actual

| Pieza | Estado |
| --- | --- |
| Contrato común (`comun/formatos.py`) | Listo, con validación |
| Banco de desarrollo: 18 servidores (6 benignos, 12 maliciosos) | Listo; compila con `tsc` y el generador lo reproduce idéntico |
| Conjunto de validación: 13 servidores (3 benignos, 10 maliciosos) | Listo; privado, fuera de git |
| Pipeline, evaluador y reporte | Listos y probados |
| Tests y CI | 15 tests pasando; CI activa en GitHub |
| Descarga de servidores públicos | Lista y probada con 100 paquetes de npm |
| Sandbox con Docker | Probado en Windows con Docker Desktop: confirma la inyección con payloads, sin marcar benignos. Aislamiento comprobado (sin red, solo lectura) |
| Frente A | Terminado: 7 categorías; 9 de 9 en desarrollo y 8 de 8 en validación, sin falsos positivos |
| Frente B (descripciones) | Placeholder que solo busca `<IMPORTANT>`; pendiente |
| Corrida para el informe y revisión manual | Listas (`corrida_informe.py`, `revision.py`) |

Resultados con el frente A terminado, el placeholder del frente B y el sandbox (22 de noviembre de 2026), sin marcar ningún benigno:

| Conjunto | Precisión | Recall |
| --- | --- | --- |
| Desarrollo (18 servidores) | 1,00 | 0,71 (10 de 14 problemas) |
| Validación (13 servidores) | 1,00 | 0,67 (8 de 12 problemas) |

Los problemas que faltan son todos del frente B (tool poisoning). En los 100 servidores reales hay 18 hallazgos en 4 servidores, pendientes de revisión manual.
