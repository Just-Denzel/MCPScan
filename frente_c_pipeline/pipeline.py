#!/usr/bin/env python3
"""Corre los analizadores sobre un corpus y escribe hallazgos.json.

Desde la raíz del repositorio:
    python -m frente_c_pipeline.pipeline <corpus> <salida.json>
        [--analizadores modulo1 modulo2 ...] [--dinamico <carpeta_sandbox>]

- Si un analizador falla en un servidor, se registra el error y la corrida sigue.
- Cada hallazgo se valida contra comun/formatos.py y se marca con su analizador.
- Junto a la salida se escribe <salida>.log.json con metadatos y errores.
El pipeline NO lee ground_truth.json: eso solo lo hace evaluar.py.
"""
import argparse
import importlib
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from comun.formatos import validar

# Para conectar un analizador nuevo: agregar aquí su módulo (debe exponer analizar()).
ANALIZADORES = [
    "frente_a_estatico.analizador",
    "frente_b_descripciones.heuristicas",
    "frente_b_descripciones.clasificador_llm",  # requiere GEMINI_API_KEY (gratis) u otra clave, o caché
]


def servidores(corpus: Path) -> list[Path]:
    return sorted(p for p in corpus.iterdir() if p.is_dir() and (p / "manifest.json").exists())


def correr(corpus: Path, modulos: list[str], dinamico: Path | None = None) -> tuple[list[dict], list[dict]]:
    """Devuelve (hallazgos, errores)."""
    mods = {m: importlib.import_module(m) for m in modulos}
    hallazgos, errores = [], []

    def agregar(h: dict, origen: str) -> None:
        h.setdefault("analizador", origen)
        problemas = validar(h)
        if problemas:
            errores.append({"analizador": origen, "servidor": h.get("servidor"),
                            "error": "hallazgo inválido: " + "; ".join(problemas)})
        else:
            hallazgos.append(h)

    for d in servidores(corpus):
        for nombre, mod in mods.items():
            try:
                resultado = mod.analizar(d)
            except Exception as e:
                errores.append({"analizador": nombre, "servidor": d.name,
                                "error": f"{type(e).__name__}: {e}",
                                "traza": traceback.format_exc(limit=3)})
                continue
            for h in resultado:
                agregar(h, nombre)

    if dinamico:
        for f in sorted(dinamico.glob("*.json")):
            datos = json.loads(f.read_text(encoding="utf-8"))
            if datos.get("error"):
                errores.append({"analizador": "sandbox", "servidor": datos.get("servidor"),
                                "error": datos["error"]})
            for h in datos.get("hallazgos", []):
                agregar(h, "sandbox")
    return hallazgos, errores


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("salida")
    ap.add_argument("--analizadores", nargs="+", default=ANALIZADORES,
                    help="módulos a correr (por defecto, todos los registrados)")
    ap.add_argument("--dinamico", help="carpeta con los .json del sandbox, cuyos hallazgos se suman")
    a = ap.parse_args()

    corpus, salida = Path(a.corpus), Path(a.salida)
    if a.dinamico and not any(Path(a.dinamico).glob("*.json")):
        sys.exit(f"La carpeta {a.dinamico} no existe o no tiene resultados del sandbox. "
                 "Corre primero frente_c_pipeline/sandbox/ejecutar.py.")
    inicio = time.time()
    hallazgos, errores = correr(corpus, a.analizadores, Path(a.dinamico) if a.dinamico else None)

    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(hallazgos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    log = salida.with_suffix(".log.json")
    log.write_text(json.dumps({
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "corpus": str(corpus),
        "servidores": len(servidores(corpus)),
        "analizadores": a.analizadores + (["sandbox"] if a.dinamico else []),
        "hallazgos": len(hallazgos),
        "segundos": round(time.time() - inicio, 1),
        "errores": errores,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    print(f"{len(hallazgos)} hallazgos escritos en {salida}")
    if errores:
        print(f"ATENCIÓN: {len(errores)} errores (detalle en {log}). Primero:\n  {errores[0]['error']}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
