#!/usr/bin/env python3
"""Reporte de riesgo por servidor a partir de hallazgos.json.

Desde la raíz:
    python -m frente_c_pipeline.reporte <hallazgos.json> <reporte.md> [--corpus <dir>] [--anonimizar]

- Puntaje: suma del peso de cada categoría distinta encontrada (alta=3, media=2, baja=1),
  tomando la severidad más alta de esa categoría en el servidor.
- --corpus incluye también los servidores sin hallazgos (para ver el total).
- --anonimizar reemplaza los nombres por S01, S02... (para el informe y la presentación).
Escribe también <reporte>.json con los mismos datos.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from comun.formatos import PESO_SEVERIDAD


def construir(hall: list[dict], todos: list[str] | None = None) -> list[dict]:
    por_srv = defaultdict(dict)  # servidor -> categoría -> severidad máxima
    evid = defaultdict(list)
    for h in hall:
        cats = por_srv[h["servidor"]]
        if PESO_SEVERIDAD[h["severidad"]] > PESO_SEVERIDAD.get(cats.get(h["categoria"]), 0):
            cats[h["categoria"]] = h["severidad"]
        evid[h["servidor"]].append(f"{h['categoria']} @ {h['ubicacion']}")
    for s in todos or []:
        por_srv.setdefault(s, {})
    filas = []
    for srv, cats in por_srv.items():
        puntaje = sum(PESO_SEVERIDAD[s] for s in cats.values())
        maxima = max(cats.values(), key=PESO_SEVERIDAD.get) if cats else "ninguna"
        filas.append({"servidor": srv, "puntaje": puntaje, "severidad_maxima": maxima,
                      "categorias": sorted(cats), "evidencia": evid[srv]})
    return sorted(filas, key=lambda f: (-f["puntaje"], f["servidor"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("hallazgos")
    ap.add_argument("salida")
    ap.add_argument("--corpus")
    ap.add_argument("--anonimizar", action="store_true")
    a = ap.parse_args()

    hall = json.loads(Path(a.hallazgos).read_text(encoding="utf-8"))
    todos = None
    if a.corpus:
        todos = [p.name for p in Path(a.corpus).iterdir() if (p / "manifest.json").exists()]
    filas = construir(hall, todos)
    if a.anonimizar:
        for i, f in enumerate(filas, 1):
            f["servidor"] = f"S{i:02d}"
            f["evidencia"] = [e.split(" @ ")[0] for e in f["evidencia"]]

    con = sum(1 for f in filas if f["puntaje"])
    lineas = [
        "# Reporte de riesgo MCPScan", "",
        f"{con} de {len(filas)} servidores con al menos un hallazgo.", "",
        "| Servidor | Puntaje | Severidad máxima | Categorías |",
        "| --- | --- | --- | --- |",
    ] + [f"| {f['servidor']} | {f['puntaje']} | {f['severidad_maxima']} | {', '.join(f['categorias']) or '—'} |"
         for f in filas]
    salida = Path(a.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
    salida.with_suffix(".json").write_text(json.dumps(filas, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8", newline="\n")
    print(f"Reporte de {len(filas)} servidores en {salida}")


if __name__ == "__main__":
    main()
