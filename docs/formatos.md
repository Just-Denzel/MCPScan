# Formatos acordados

Las tres partes del proyecto se conectan solo por estos formatos. **La fuente de verdad es `comun/formatos.py`**; este documento lo explica. Si hay que cambiar algo, se avisa al grupo antes.

## 1. Corpus

El corpus es la colección de servidores que se analizan. Una carpeta por servidor, con la misma estructura en todas, incluidos los del banco de pruebas, para que el pipeline no distinga entre uno real y uno de prueba.

```
corpus/<conjunto>/
  <servidor>/
    manifest.json        datos básicos del servidor
    codigo/              el paquete descomprimido
    herramientas.json    nombre, descripción y esquema de cada herramienta
```

`manifest.json`:

```json
{
  "nombre": "servidor-ejemplo",
  "fuente": "npm",
  "version": "1.2.0",
  "repositorio": "https://github.com/...",
  "fecha_descarga": "2026-11-09",
  "tiene_codigo": true
}
```

`herramientas.json` es una lista:

```json
[
  {
    "nombre": "sumar",
    "descripcion": "Suma dos números.",
    "esquema": { "type": "object", "properties": { "a": { "type": "number" } }, "required": ["a"] }
  }
]
```

- Las descripciones de los **parámetros** van en `esquema.properties.<parámetro>.description`. El modelo también las lee, así que el frente B debe revisarlas.
- El banco de pruebas trae `herramientas.json` listo. Los servidores reales descargados de npm **no lo traen**: `frente_b_descripciones/extractor.py` lo reconstruye leyendo el código (ver `frente_b_descripciones/README.md`). Las herramientas extraídas traen dos campos más: `origen` (`codigo/<archivo>:<línea>` donde se definen) y `patron` (cómo se encontraron).
- `fuente` es `npm` para los reales y `local` para los del banco de pruebas.

## 2. Hallazgo

Cada vez que una regla o el clasificador detecta algo, se crea con `comun.formatos.hallazgo(...)`:

```json
{
  "servidor": "servidor-ejemplo",
  "categoria": "ejecucion-de-comando",
  "regla": "exec-con-plantilla",
  "severidad": "alta",
  "evidencia": "exec(`ping -c 1 ${host}`)",
  "ubicacion": "codigo/src/index.ts:16",
  "analizador": "frente_a_estatico.analizador"
}
```

| Campo | Qué es |
| --- | --- |
| `categoria` | Una de la tabla de abajo. Es lo que compara el evaluador. |
| `regla` | Nombre libre de la regla o heurística concreta (varias reglas pueden dar la misma categoría). |
| `severidad` | `alta`, `media` o `baja`. |
| `evidencia` | El fragmento que gatilló el hallazgo (se recorta a 300 caracteres). |
| `ubicacion` | `ruta:línea` relativa a la carpeta del servidor; para descripciones, `herramientas.json:<herramienta>`. |
| `analizador` | Lo agrega el pipeline: el módulo que produjo el hallazgo. Sirve para comparar técnicas. |

## 3. Categorías

| Categoría | Qué significa | Frente |
| --- | --- | --- |
| `ejecucion-de-comando` | Dato del modelo llega a un comando de shell | A |
| `exfiltracion-red` | Envía datos (variables de entorno, usuario, etc.) a un dominio externo | A |
| `lectura-archivo-sensible` | Lee `~/.ssh`, `~/.aws`, `.env`, etc. | A (estático) y sandbox (dinámico) |
| `secreto-hardcodeado` | Claves o credenciales en el código | A |
| `dependencia-typosquat` | Dependencia con nombre parecido a una popular | A |
| `script-instalacion` | `preinstall`, `install` o `postinstall` en `package.json` | A |
| `codigo-ofuscado` | Código oculto (base64, códigos de caracteres) ejecutado con `eval` o `new Function` | A |
| `tool-poisoning-instruccion` | Instrucción evidente dirigida al modelo en una descripción | B |
| `tool-poisoning-unicode` | Texto oculto en caracteres Unicode invisibles | B |
| `tool-poisoning-parafraseado` | Instrucción reformulada, sin palabras clave típicas | B |

Qué cuenta y qué no en cada categoría, con sus variantes: ver **[docs/categorias.md](categorias.md)**.

Para agregar una categoría: agregarla en `comun/formatos.py`, en el ground truth (`frente_c_pipeline/generar_banco.py`) y en esta tabla.

## 4. Ground truth

`corpus/banco_de_pruebas/ground_truth.json` indica, para cada servidor de prueba, si es benigno o malicioso y qué hallazgos se esperan (categoría, archivo, línea). **Los analizadores no deben leerlo**; solo lo usa `evaluar.py`.

El evaluador cuenta un acierto cuando coinciden **servidor y categoría**. Varios hallazgos de la misma categoría en el mismo servidor cuentan como uno.
