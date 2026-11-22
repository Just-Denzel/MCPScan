"""Lectura de las definiciones de herramientas de un servidor del corpus.

Lo usan las heurísticas y el clasificador LLM, para que las dos técnicas vean exactamente
los mismos textos:

- cargar(dir_servidor): la lista de herramientas de <servidor>/herramientas.json.
- textos(herramienta): cada texto que lee el modelo, con dónde está: la descripción de la
  herramienta y la de cada parámetro (esquema.properties.<p>.description), también anidados.
- ubicacion(dir_servidor, herramienta, donde): el campo "ubicacion" del hallazgo.
"""
import json
from pathlib import Path

# Claves de JSON Schema que contienen subesquemas con más parámetros.
_SUBESQUEMAS_DICT = ("properties", "patternProperties", "definitions", "$defs")
_SUBESQUEMAS_LISTA = ("anyOf", "oneOf", "allOf", "prefixItems")
_SUBESQUEMAS_UNO = ("items", "additionalProperties", "not")


def cargar(dir_servidor: Path) -> list[dict]:
    """Herramientas del servidor (lista vacía si no hay herramientas.json o está mal formado)."""
    f = Path(dir_servidor) / "herramientas.json"
    if not f.exists():
        return []
    try:
        datos = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(datos, list):
        return []
    return [h for h in datos if isinstance(h, dict) and h.get("nombre")]


def _textos_esquema(esquema, ruta: str):
    if not isinstance(esquema, dict):
        return
    if ruta and isinstance(esquema.get("description"), str) and esquema["description"].strip():
        yield f"parametro:{ruta}", esquema["description"]
    if ruta and isinstance(esquema.get("title"), str) and esquema["title"].strip():
        yield f"parametro:{ruta}#title", esquema["title"]
    for clave in _SUBESQUEMAS_DICT:
        hijos = esquema.get(clave)
        if isinstance(hijos, dict):
            for nombre, sub in hijos.items():
                yield from _textos_esquema(sub, f"{ruta}.{nombre}" if ruta else str(nombre))
    for clave in _SUBESQUEMAS_LISTA:
        hijos = esquema.get(clave)
        if isinstance(hijos, list):
            for i, sub in enumerate(hijos):
                yield from _textos_esquema(sub, f"{ruta}[{i}]" if ruta else f"[{i}]")
    for clave in _SUBESQUEMAS_UNO:
        sub = esquema.get(clave)
        if isinstance(sub, dict):
            yield from _textos_esquema(sub, f"{ruta}[]" if ruta else "[]")


def textos(herramienta: dict):
    """Genera (donde, texto): 'descripcion' o 'parametro:<ruta>' (por ejemplo 'parametro:opciones.modo')."""
    d = herramienta.get("descripcion")
    if isinstance(d, str) and d.strip():
        yield "descripcion", d
    t = herramienta.get("titulo")
    if isinstance(t, str) and t.strip():
        yield "titulo", t
    yield from _textos_esquema(herramienta.get("esquema"), "")


def parametros(herramienta: dict) -> dict:
    """{nombre: subesquema} de los parámetros de primer nivel."""
    esquema = herramienta.get("esquema")
    if isinstance(esquema, dict) and isinstance(esquema.get("properties"), dict):
        return {k: v for k, v in esquema["properties"].items() if isinstance(v, dict)}
    return {}


def ubicacion(herramienta: dict, donde: str) -> str:
    """'herramientas.json:<nombre>' (o '<nombre>/<parámetro>'); si vino del extractor, 'ruta:línea' del código."""
    if herramienta.get("origen"):
        return str(herramienta["origen"])
    sufijo = "" if donde in ("descripcion", "titulo") else "/" + donde.split(":", 1)[1]
    return f"herramientas.json:{herramienta['nombre']}{sufijo}"
