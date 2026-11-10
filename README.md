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
│   └── formatos.md              El contrato explicado (leer primero)
├── corpus/
│   ├── banco_de_pruebas/        13 servidores propios + ground_truth.json (versionado)
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
│   ├── generar_banco.py         regenera el banco de pruebas
│   └── sandbox/                 Dockerfile, cliente MCP y ejecutor
├── tests/                       pytest: contrato, banco de pruebas, pipeline
├── .github/workflows/ci.yml     corre los tests y compila el banco en cada push
└── resultados/                  salidas de las corridas (NO se suben a git)
```

Cada frente tiene su propio README con qué entregar, qué falta y cómo probarlo.

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
| Banco de pruebas: 13 servidores (5 benignos, 8 maliciosos) | Listo; compila con `tsc` y el generador lo reproduce idéntico |
| Pipeline, evaluador y reporte | Listos y probados |
| Tests y CI | 11 tests pasando; CI escrita (se activa al subir a GitHub) |
| Descarga de servidores públicos | Lista y probada con 100 paquetes de npm |
| Sandbox con Docker | Probado en Windows con Docker Desktop: 13 servidores, detecta `lectura-archivos-sensibles`, ningún benigno marcado. Falta confirmar el aislamiento (ver `frente_c_pipeline/README.md`) |
| Frente A (reglas) | Una regla de ejemplo; faltan las demás |
| Frente B (descripciones) | Placeholder que solo busca `<IMPORTANT>` |

Con los analizadores de ejemplo y el sandbox, el banco de pruebas da precisión 1,00 y recall 0,30 (3 de 10 problemas esperados), sin marcar ningún benigno. Resultado reproducido en Windows el 9 de noviembre de 2026.
