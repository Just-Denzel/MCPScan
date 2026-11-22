# Frente B: tool poisoning en las descripciones

Detecta instrucciones ocultas dirigidas al modelo dentro del texto que describe cada herramienta y cada parámetro. El modelo lee esa descripción; el usuario normalmente no.

## Qué hay en esta carpeta

| Archivo | Qué hace |
| --- | --- |
| `herramientas.py` | Lee las herramientas de un servidor y entrega cada texto que ve el modelo (descripción y parámetros, también anidados). Lo usan las dos técnicas, así que ven exactamente lo mismo. Si el servidor no trae `herramientas.json`, las extrae del código. |
| `heuristicas.py` | Técnica 1: heurísticas. `analizar()` para el pipeline. |
| `clasificador_llm.py` | Técnica 2: LLM-as-judge. `analizar()` para el pipeline. |
| `prompts/clasificador_v2.md` | Prompt del clasificador (la v1 queda como historial). |
| `extractor.py` | Extrae nombre, descripción y esquema de cada herramienta leyendo el código de los servidores reales, sin ejecutarlo. |
| `comparar.py` | Compara las dos técnicas: precisión y recall, qué detecta cada una, costo y consistencia del LLM. |
| `analizador.py` | Nombre antiguo (era el placeholder). Ahora corre las heurísticas; se mantiene para no romper comandos ni tests. |

Los tests están en `tests/test_frente_b.py`.

## Cómo correrlo

Desde la raíz del repositorio:

```bash
# Las dos técnicas en el pipeline (ya están registradas en ANALIZADORES)
python -m frente_c_pipeline.pipeline corpus/banco_de_pruebas resultados/b.json --analizadores frente_b_descripciones.heuristicas frente_b_descripciones.clasificador_llm
python -m frente_c_pipeline.evaluar corpus/banco_de_pruebas/ground_truth.json resultados/b.json

# Comparación de técnicas (tablas para el informe en resultados/frente_b/<fecha>/comparacion.md)
python -m frente_b_descripciones.comparar corpus/banco_de_pruebas --repeticiones 3
python -m frente_b_descripciones.comparar corpus/real --repeticiones 3
python -m frente_b_descripciones.comparar corpus/real --sin-llm        # sin clave de API

# Extraer las herramientas de los servidores reales a herramientas.json (opcional: el pipeline
# las extrae solo si falta el archivo; esto sirve para revisarlas y para el % del informe)
python -m frente_b_descripciones.extractor corpus/real --resumen resultados/extraccion_real.json
```

### Clave de API del clasificador

La clave va en una variable de entorno, **nunca en el repositorio**:

```bash
export ANTHROPIC_API_KEY=...          # PowerShell: $env:ANTHROPIC_API_KEY="..."
```

Por defecto usa `claude-haiku-5-5` con temperatura 0. Se puede cambiar con `MCPSCAN_LLM_MODELO`, o usar un proveedor compatible con OpenAI con `OPENAI_API_KEY`, `MCPSCAN_LLM_PROVEEDOR=openai`, `MCPSCAN_LLM_MODELO` y, si no es OpenAI, `MCPSCAN_LLM_URL`. El resto de las opciones está al inicio de `clasificador_llm.py`.

Cada respuesta se guarda en `resultados/cache_llm/` con sus tokens, costo y tiempo. Repetir una corrida no vuelve a pagar, y si alguien comparte esa carpeta, los demás reproducen sus resultados sin clave. Sin clave y sin caché, el clasificador falla con un mensaje claro en cada servidor (el pipeline lo registra y sigue); para correr solo lo demás, usar `--analizadores`.

Costo estimado con Haiku 5.5: unos 20 mil tokens de entrada para el banco y unos 300 mil para los 88 servidores reales con herramientas, es decir, cerca de 0,03 USD por repetición sobre la muestra real.

## Heurísticas

Escritas contra [docs/categorias.md](../docs/categorias.md), no contra los ejemplos del banco. Cada texto pasa por tres pasos:

1. **Unicode invisible** (`tool-poisoning-unicode`): caracteres del bloque *tags*, de ancho cero (también intercalados entre letras) y controles de dirección. El texto escondido en *tags* se decodifica y va en la evidencia. Se exceptúan los usos legítimos en emojis (secuencias con ZWJ, banderas de subdivisiones) y en escrituras no latinas.
2. **Señales de instrucción** sobre el texto visible normalizado (minúsculas, sin tildes ni invisibles), en español e inglés. Cada señal suma puntos y se marca desde 3:
   - etiquetas tipo `<IMPORTANT>` o comentarios HTML; "ignora las instrucciones";
   - pedir que no se informe al usuario (la frase tiene que hablar del usuario);
   - leer o enviar un recurso sensible (claves SSH, `~/.aws`, `.env`, credenciales, historial, variables de entorno) **en la misma frase que un verbo de acceso**, y no negado ("nunca lee credenciales") ni protegido ("deja las credenciales fuera");
   - pedir que ese recurso vaya en un parámetro o campo;
   - manipular otras herramientas u otros servidores (*tool shadowing*), destinatarios o URLs a los que enviar datos;
   - texto escondido después de muchas líneas o espacios en blanco;
   - parámetros con nombre de canal (`contexto`, `notas`...) que la herramienta no necesita.

   Una orden sola ("debes pedir confirmación antes de borrar") no basta: al menos una señal tiene que mostrar intención (ocultar, sacar datos, manipular otra herramienta).
3. **Categoría según la forma**: `tool-poisoning-instruccion` si hay marcas explícitas (etiquetas, imperativos como "lee ~/.ssh/id_rsa", "no menciones", "debes", "el asistente debe", manipulación de otras herramientas); `tool-poisoning-parafraseado` si la misma intención está redactada como recomendación o paso de rutina ("conviene que", "el usuario prefiere").

## Clasificador LLM

- Una llamada por servidor con todas sus herramientas (en lotes si son muchas, para no pasar de ~40 mil tokens), así el modelo ve si una descripción intenta manipular a otra herramienta.
- Las descripciones van como JSON dentro de `<herramientas_{nonce}>`, con un sufijo que depende del contenido: una descripción maliciosa no puede cerrar la etiqueta. Los nombres de herramienta que no existen en la respuesta se descartan.
- Respuesta en JSON con forma (`explicita` → instrucción, `encubierta` → parafraseado), `texto_oculto` (→ unicode), dónde, severidad y razón. Si la respuesta no es JSON, se pide una vez más.
- `--repeticiones N` en `comparar.py` (o `MCPSCAN_LLM_REPETICIONES` en el pipeline) llama N veces y decide por mayoría; la comparación reporta qué fracción de herramientas recibió el mismo veredicto en todas.
- El JSON se envía sin escapar los caracteres invisibles, para medir si el modelo los ve (hipótesis del caso `poison-unicode-invisible`).

## Extractor de herramientas de los servidores reales

Los paquetes de npm no traen `herramientas.json`. `extractor.py` tokeniza el JavaScript o TypeScript del paquete (también `dist/` minificado) y evalúa solo un subconjunto seguro de expresiones: textos, plantillas, concatenación, `.join()`, `dedent`, constantes del mismo archivo o del paquete, objetos, listas, y cadenas de zod o TypeBox para los parámetros. No ejecuta nada. Reconoce `registerTool(...)`, `server.tool(...)`, envoltorios propios con la misma forma, objetos `{ name, description, inputSchema | handler }` y mapas de descripciones aparte. Lo que depende de código (variables de entorno, datos de la red) queda como `${…}` en el texto.

Cada herramienta extraída trae además `origen` (archivo y línea, que se usa como `ubicacion` de los hallazgos) y `patron`. El extractor nunca toca los servidores del banco ni un `herramientas.json` que no haya escrito él.

| Conjunto | Servidores con herramientas | Herramientas | Descripción completa | Parcial (`${…}`) |
| --- | --- | --- | --- | --- |
| Banco de desarrollo | 18 de 18 | 20 | reproduce los 18 `herramientas.json` idénticos | — |
| Muestra real (22-11-2026) | 88 de 100 (88 %) | 1.346 | 96,4 % | 2,5 % |
| Muestra de control | 51 de 67 (76 %) | 859 | 82,0 % | 16,8 % |

Los servidores sin herramientas son sobre todo envoltorios de binarios (Go, Rust), servidores que bajan su catálogo de herramientas desde la red al arrancar o que las generan desde datos; ninguno se puede resolver sin ejecutar código.

## Resultados al 22 de noviembre de 2026

Banco de desarrollo, solo las categorías de B:

| Servidor | Esperado | Heurísticas | LLM |
| --- | --- | --- | --- |
| `poison-instruccion-oculta` | instrucción | ✓ | pendiente |
| `poison-unicode-invisible` | unicode | ✓ | pendiente |
| `poison-parafraseado` | parafraseado | ✓ | pendiente |
| `poison-parametro` | instrucción | ✓ | pendiente |
| `poison-otra-herramienta` | instrucción | ✓ | pendiente |
| benignos (incluido `benigno-busqueda-proyecto`) | nada | sin falsos positivos | pendiente |

Con el frente A, el pipeline completo queda en precisión 1,00 y recall 1,00 en desarrollo (14 de 14 problemas, 0 benignos marcados).

En los servidores reales, las heurísticas no marcan nada en los 88 de la muestra ni en los 51 de control con herramientas. **Ojo al citarlo:** la primera versión marcaba 16 descripciones legítimas en 11 servidores (instrucciones de uso normales: "nunca reportes...", "usa X en lugar de Y", "deja las credenciales fuera"), y las reglas se ajustaron mirando esos casos, también los de la muestra de control. Ese 0 no es una medida independiente de falsos positivos; la medida limpia es el conjunto de validación privado del frente C.

Las columnas del LLM quedan pendientes: hay que correr `comparar.py` con una clave de API.

## Limitaciones (para el informe)

- Las heurísticas solo conocen español e inglés: la misma instrucción en portugués u otro idioma se les escapa. Es la familia "en otro idioma" de `parafraseado`, donde se espera que gane el LLM.
- Distinguir instrucción explícita de parafraseada por la redacción es frágil; una orden con tono amable puede caer en la otra categoría.
- El extractor ve el código, no lo que el servidor entrega en ejecución: descripciones armadas con datos de la red o del entorno quedan incompletas, y un servidor podría mostrar una descripción en el código y otra distinta al correr (*rug pull*, extensión propuesta).
- Cuando el texto escondido en Unicode es además una instrucción, se reporta solo como `tool-poisoning-unicode`, igual que en el ground truth del banco (la especificación dice que también podría contar como instrucción).
