#!/usr/bin/env python3
"""Compara hallazgos.json con ground_truth.json: precisión, recall y qué detecta cada analizador.

Desde la raíz:
    python -m frente_c_pipeline.evaluar <ground_truth.json> <hallazgos.json> [--json metricas.json]

Un acierto es un par (servidor, categoría) esperado que aparece en los hallazgos.
Varios hallazgos de la misma categoría en el mismo servidor cuentan como uno.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from comun.formatos import CATEGORIAS


def metricas(esperados: set, obtenidos: set) -> dict:
    tp, fp, fn = esperados & obtenidos, obtenidos - esperados, esperados - obtenidos
    p = len(tp) / (len(tp) + len(fp)) if (tp or fp) else None
    r = len(tp) / (len(tp) + len(fn)) if (tp or fn) else None
    return {"tp": len(tp), "fp": len(fp), "fn": len(fn), "precision": p, "recall": r,
            "_tp": tp, "_fp": fp, "_fn": fn}


def evaluar(gt: dict, hall: list[dict]) -> dict:
    servs = gt["servidores"]
    esperados = {(s["servidor"], h["categoria"]) for s in servs for h in s["hallazgos_esperados"]}
    obtenidos = {(h["servidor"], h["categoria"]) for h in hall}
    glob = metricas(esperados, obtenidos)

    por_cat = {}
    for cat in sorted({c for _, c in esperados | obtenidos}):
        por_cat[cat] = metricas({e for e in esperados if e[1] == cat}, {o for o in obtenidos if o[1] == cat})

    # Qué detecta cada analizador: base de la comparación de técnicas.
    por_analizador = defaultdict(set)
    for h in hall:
        por_analizador[h.get("analizador", "?")].add((h["servidor"], h["categoria"]))
    analizadores = {a: {"aciertos": len(o & esperados), "falsos_positivos": len(o - esperados),
                        "_obt": o} for a, o in sorted(por_analizador.items())}

    marcados = {h["servidor"] for h in hall}
    mal = {s["servidor"] for s in servs if s["etiqueta"] == "malicioso"}
    ben = {s["servidor"] for s in servs if s["etiqueta"] == "benigno"}
    return {
        "global": glob, "por_categoria": por_cat, "por_analizador": analizadores,
        "esperados": esperados,
        "servidores": {"maliciosos_detectados": len(mal & marcados), "maliciosos": len(mal),
                       "benignos_marcados": len(ben & marcados), "benignos": len(ben),
                       "benignos_marcados_lista": sorted(ben & marcados)},
        "categorias_desconocidas": sorted({h["categoria"] for h in hall} - set(CATEGORIAS)),
    }


def _corto(modulo: str) -> str:
    """frente_a_estatico.analizador -> A:analizador; frente_b_descripciones.heuristicas -> B:heuristicas."""
    partes = modulo.split(".")
    if partes[0].startswith("frente_") and len(partes[0]) > 7:
        return f"{partes[0][7].upper()}:{partes[-1]}"[:12]
    return modulo[:12]


def _f(x) -> str:
    return "  —  " if x is None else f"{x:.2f}"


def imprimir(r: dict) -> None:
    g = r["global"]
    print(f"GLOBAL  aciertos: {g['tp']}  falsos+: {g['fp']}  falsos-: {g['fn']}  "
          f"precisión: {_f(g['precision'])}  recall: {_f(g['recall'])}")
    s = r["servidores"]
    print(f"Servidores: maliciosos detectados {s['maliciosos_detectados']}/{s['maliciosos']}, "
          f"benignos marcados por error {s['benignos_marcados']}/{s['benignos']}"
          + (f" {s['benignos_marcados_lista']}" if s["benignos_marcados_lista"] else ""))
    if r["categorias_desconocidas"]:
        print(f"ATENCIÓN: categorías que no existen en comun/formatos.py: {r['categorias_desconocidas']}")

    print("\nPor categoría:")
    for cat, m in r["por_categoria"].items():
        print(f"  {cat:30} aciertos={m['tp']} falsos+={m['fp']} falsos-={m['fn']}  "
              f"prec={_f(m['precision'])} rec={_f(m['recall'])}")

    ans = r["por_analizador"]
    if ans:
        print("\nMatriz de detección (✓ = ese analizador encontró el problema esperado):")
        cortos = {a: _corto(a) for a in ans}
        print(f"  {'servidor / categoría':58}" + "".join(f"{cortos[a]:>13}" for a in ans))
        for srv, cat in sorted(r["esperados"]):
            fila = "".join(f"{('✓' if (srv, cat) in ans[a]['_obt'] else '·'):>13}" for a in ans)
            print(f"  {(srv + ' / ' + cat)[:58]:58}{fila}")
        print("  " + " " * 58 + "".join(f"{'FP=' + str(ans[a]['falsos_positivos']):>13}" for a in ans))

    if g["_fp"]:
        print("\nFalsos positivos:", *sorted(g["_fp"]), sep="\n  ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ground_truth")
    ap.add_argument("hallazgos")
    ap.add_argument("--json", help="guarda las métricas en este archivo (para el informe)")
    a = ap.parse_args()
    gt = json.loads(Path(a.ground_truth).read_text(encoding="utf-8"))
    hall = json.loads(Path(a.hallazgos).read_text(encoding="utf-8"))
    r = evaluar(gt, hall)
    imprimir(r)
    if a.json:
        limpio = {k: v for k, v in r.items() if k != "esperados"}
        limpio["global"] = {k: v for k, v in r["global"].items() if not k.startswith("_")}
        limpio["por_categoria"] = {c: {k: v for k, v in m.items() if not k.startswith("_")}
                                   for c, m in r["por_categoria"].items()}
        limpio["por_analizador"] = {a_: {k: v for k, v in m.items() if not k.startswith("_")}
                                    for a_, m in r["por_analizador"].items()}
        Path(a.json).write_text(json.dumps(limpio, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
