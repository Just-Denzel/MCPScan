"""Frente B: análisis de las descripciones de herramientas (tool poisoning).

Contrato con el pipeline: analizar(dir_servidor) -> lista de hallazgos (ver docs/formatos.md).
Lee <servidor>/herramientas.json. Esta versión inicial es un PLACEHOLDER que solo
busca '<IMPORTANT>'; se reemplaza por las heurísticas y el clasificador LLM.
"""
import json
from pathlib import Path

from comun.formatos import hallazgo


def analizar(dir_servidor: Path) -> list[dict]:
    f = dir_servidor / "herramientas.json"
    if not f.exists():
        return []
    salida = []
    for t in json.loads(f.read_text(encoding="utf-8")):
        if "<IMPORTANT>" in t["descripcion"].upper():
            salida.append(hallazgo(
                servidor=dir_servidor.name,
                categoria="tool-poisoning-instruccion",
                regla="etiqueta-important",
                severidad="alta",
                evidencia=t["descripcion"],
                ubicacion=f"herramientas.json:{t['nombre']}",
            ))
    # TODO (frente B): heurísticas (Unicode invisible, rutas sensibles, ...) y clasificador LLM,
    # idealmente como módulos separados para poder compararlos.
    return salida
