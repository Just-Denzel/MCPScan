#!/usr/bin/env python3
"""Resume la revisión manual de los hallazgos en servidores reales.

1. Abre revision_manual.csv (de corrida_informe) en Excel y, para cada hallazgo, escribe en
   la columna "veredicto":
     verdadero  el problema existe (por ejemplo, un dato del modelo llega de verdad a exec)
     falso      no es un problema (por ejemplo, el comando es fijo o lo controla el autor)
     dudoso     no se puede decidir leyendo el código
   y en "nota" una frase con el porqué (sirve para el informe).
2. Desde la raíz:
       python -m frente_c_pipeline.revision resultados/informe/<fecha>/revision_manual.csv

Imprime la precisión estimada en servidores reales (verdaderos / (verdaderos + falsos)),
global, por categoría y por regla. Escribe también revision_resumen.md junto al CSV.
"""
import argparse
import csv
import unicodedata
from collections import defaultdict
from pathlib import Path

SINONIMOS = {
    "verdadero": "verdadero", "v": "verdadero", "si": "verdadero", "vp": "verdadero", "tp": "verdadero",
    "falso": "falso", "f": "falso", "no": "falso", "fp": "falso",
    "dudoso": "dudoso", "d": "dudoso", "?": "dudoso",
}


def _normalizar(v: str) -> str:
    v = unicodedata.normalize("NFKD", v.strip().lower()).encode("ascii", "ignore").decode()
    return SINONIMOS.get(v, "pendiente" if not v else "invalido")


def leer(ruta: Path) -> list[dict]:
    texto = ruta.read_text(encoding="utf-8-sig")
    delim = ";" if texto.split("\n", 1)[0].count(";") >= texto.split("\n", 1)[0].count(",") else ","
    return list(csv.DictReader(texto.splitlines(), delimiter=delim))


def resumir(filas: list[dict]) -> dict:
    def vacio():
        return {"verdadero": 0, "falso": 0, "dudoso": 0, "pendiente": 0, "invalido": 0}
    total, por_cat, por_regla = vacio(), defaultdict(vacio), defaultdict(vacio)
    invalidos = []
    for f in filas:
        v = _normalizar(f.get("veredicto", ""))
        if v == "invalido":
            invalidos.append((f.get("id"), f.get("veredicto")))
        for d in (total, por_cat[f["categoria"]], por_regla[f["regla"]]):
            d[v] += 1
    return {"total": total, "por_categoria": dict(por_cat), "por_regla": dict(por_regla), "invalidos": invalidos}


def _precision(d: dict) -> str:
    n = d["verdadero"] + d["falso"]
    return "—" if not n else f"{d['verdadero'] / n:.2f}".replace(".", ",")


def tabla(titulo: str, grupos: dict) -> list[str]:
    lineas = [f"## {titulo}", "", "| | Verdaderos | Falsos | Dudosos | Pendientes | Precisión estimada |",
              "| --- | --- | --- | --- | --- | --- |"]
    for nombre, d in sorted(grupos.items()):
        lineas.append(f"| {nombre} | {d['verdadero']} | {d['falso']} | {d['dudoso']} | {d['pendiente']} | {_precision(d)} |")
    return lineas + [""]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ruta = Path(ap.parse_args().csv)
    r = resumir(leer(ruta))
    t = r["total"]
    lineas = ["# Revisión manual de hallazgos en servidores reales", "",
              f"{sum(t.values())} hallazgos: {t['verdadero']} verdaderos, {t['falso']} falsos, "
              f"{t['dudoso']} dudosos y {t['pendiente']} pendientes. "
              f"Precisión estimada: {_precision(t)} (verdaderos / (verdaderos + falsos); los dudosos no cuentan).", ""]
    lineas += tabla("Por categoría", r["por_categoria"]) + tabla("Por regla", r["por_regla"])
    salida = ruta.with_name("revision_resumen.md")
    salida.write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lineas))
    if t["pendiente"]:
        print(f"Faltan {t['pendiente']} hallazgos por revisar.")
    if r["invalidos"]:
        print("Veredictos no reconocidos (usa verdadero, falso o dudoso):",
              ", ".join(f"id {i}: '{v}'" for i, v in r["invalidos"]))
    print(f"Resumen guardado en {salida}")


if __name__ == "__main__":
    main()
