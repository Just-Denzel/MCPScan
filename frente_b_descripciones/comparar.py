#!/usr/bin/env python3
"""Compara las heurísticas con el clasificador LLM en la detección de tool poisoning.

Desde la raíz del repositorio:
    python -m frente_b_descripciones.comparar <corpus> [--repeticiones 3] [--sin-llm] [--salida resultados/frente_b]

- Si el corpus tiene ground_truth.json (banco de pruebas, validación), calcula precisión y recall
  de cada técnica solo sobre las categorías del frente B, y la matriz de qué detecta cada una.
- Si no lo tiene (servidores reales), cuenta hallazgos y separa los que marcan las dos técnicas,
  solo una o solo la otra, y deja un CSV para revisarlos a mano.
- Del LLM mide además la consistencia entre repeticiones (mismo veredicto en todas), el costo
  por servidor y el tiempo. Las respuestas quedan en caché: repetir la comparación no vuelve a pagar.

Deja en <salida>/<fecha_hora>/: comparacion.md (tablas para el informe), comparacion.json,
hallazgos_heuristicas.json, hallazgos_llm.json y, en reales, revision_b.csv (PRIVADO: nombres reales).
"""
import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

from comun.formatos import CATEGORIAS
from frente_b_descripciones import clasificador_llm, heuristicas
from frente_b_descripciones.herramientas import cargar
from frente_c_pipeline.evaluar import evaluar
from frente_c_pipeline.pipeline import servidores

CATEGORIAS_B = {c for c, (frente, _) in CATEGORIAS.items() if frente == "B"}


def _f(x) -> str:
    return "—" if x is None else f"{x:.2f}".replace(".", ",")


def _correr_heuristicas(dirs: list[Path]) -> tuple[list[dict], float]:
    inicio, hall = time.time(), []
    for d in dirs:
        for h in heuristicas.analizar(d):
            hall.append({**h, "analizador": "heuristicas"})
    return hall, time.time() - inicio


def _correr_llm(dirs: list[Path], repeticiones: int) -> dict:
    """Corre el LLM con N repeticiones. Devuelve hallazgos (por mayoría), consistencia, costo y errores."""
    cfg = clasificador_llm.configuracion()
    clasificador_llm.ESTADISTICAS.clear()
    hall, errores = [], []
    herramientas_tot, unanimes, servidores_unanimes, con_herr = 0, 0, 0, 0
    inicio = time.time()
    for d in dirs:
        hs = {h["nombre"]: h for h in cargar(d)}
        if not hs:
            continue
        con_herr += 1
        try:
            por_rep = clasificador_llm.veredictos(d, repeticiones, cfg)
        except clasificador_llm.ErrorLLM as e:
            errores.append({"servidor": d.name, "error": str(e)})
            continue
        # Consistencia: cada herramienta, ¿recibió la misma categoría (o ninguna) en todas las repeticiones?
        cats = [{s["nombre"]: clasificador_llm.categoria(s) for s in rep} for rep in por_rep]
        iguales = [len({c.get(n) for c in cats}) == 1 for n in hs]
        herramientas_tot += len(iguales)
        unanimes += sum(iguales)
        servidores_unanimes += all(iguales)
        for s in clasificador_llm.votar(por_rep):
            hall.append({**clasificador_llm.a_hallazgo(d.name, hs[s["nombre"]], s), "analizador": "clasificador_llm"})
    est = clasificador_llm.ESTADISTICAS
    costos = [e["costo_usd"] for e in est if e["costo_usd"] is not None]
    pagadas = [e for e in est if not e["cache"]]
    return {
        "hallazgos": hall, "errores": errores, "modelo": cfg["modelo"], "proveedor": cfg["proveedor"],
        "prompt": clasificador_llm.VERSION_PROMPT, "temperatura": cfg["temperatura"], "repeticiones": repeticiones,
        "llamadas": len(est), "desde_cache": len(est) - len(pagadas),
        "tokens_entrada": sum(e["tokens_entrada"] for e in est), "tokens_salida": sum(e["tokens_salida"] for e in est),
        "costo_total_usd": round(sum(costos), 6) if costos else None,
        "costo_por_servidor_usd": round(sum(costos) / con_herr / repeticiones, 6) if costos and con_herr else None,
        "segundos_por_llamada": round(sum(e["segundos"] for e in est) / len(est), 2) if est else None,
        "segundos_total": round(time.time() - inicio, 1),
        "consistencia_herramientas": round(unanimes / herramientas_tot, 3) if herramientas_tot else None,
        "consistencia_servidores": round(servidores_unanimes / (con_herr - len(errores)), 3)
        if con_herr - len(errores) > 0 else None,
    }


def _solo_b(gt: dict) -> dict:
    return {"servidores": [{**s, "hallazgos_esperados": [h for h in s["hallazgos_esperados"]
                                                          if h["categoria"] in CATEGORIAS_B]}
                           for s in gt["servidores"]]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("corpus")
    ap.add_argument("--repeticiones", type=int, default=3, help="llamadas al LLM por servidor (consistencia)")
    ap.add_argument("--sin-llm", action="store_true", help="solo heurísticas (sin clave de API)")
    ap.add_argument("--salida", default="resultados/frente_b")
    a = ap.parse_args()

    corpus = Path(a.corpus)
    dirs = servidores(corpus)
    out = Path(a.salida) / datetime.now().strftime("%Y-%m-%d_%H%M")
    out.mkdir(parents=True, exist_ok=True)
    escribir = lambda nombre, datos: (out / nombre).write_text(
        json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    con_herr = sum(1 for d in dirs if cargar(d))
    print(f"{len(dirs)} servidores en {corpus}, {con_herr} con herramientas para analizar")
    hall_h, seg_h = _correr_heuristicas(dirs)
    print(f"  heurísticas: {len(hall_h)} hallazgos en {seg_h:.1f} s")
    llm = None
    if not a.sin_llm:
        llm = _correr_llm(dirs, a.repeticiones)
        print(f"  LLM ({llm['modelo']}): {len(llm['hallazgos'])} hallazgos, {llm['llamadas']} llamadas "
              f"({llm['desde_cache']} desde caché), costo {llm['costo_total_usd']} USD, errores: {len(llm['errores'])}")
        if llm["errores"]:
            print(f"  ATENCIÓN: primer error del LLM: {llm['errores'][0]['error']}")
    escribir("hallazgos_heuristicas.json", hall_h)
    tecnicas = {"heuristicas": hall_h}
    if llm:
        escribir("hallazgos_llm.json", llm["hallazgos"])
        tecnicas["clasificador_llm"] = llm["hallazgos"]

    t = [f"# Comparación de técnicas del frente B: {corpus.name}", "",
         f"Corrida del {datetime.now():%d-%m-%Y %H:%M}. {len(dirs)} servidores, {con_herr} con herramientas.", ""]
    resultado = {"corpus": str(corpus), "servidores": len(dirs), "con_herramientas": con_herr,
                 "heuristicas_segundos": round(seg_h, 2)}

    gt_ruta = corpus / "ground_truth.json"
    if gt_ruta.exists():
        gt = _solo_b(json.loads(gt_ruta.read_text(encoding="utf-8")))
        evals = {n: evaluar(gt, [h for h in hs if h["categoria"] in CATEGORIAS_B]) for n, hs in tecnicas.items()}
        t += ["## Precisión y recall (solo categorías del frente B)", "",
              "| Técnica | Aciertos | Falsos + | Falsos − | Precisión | Recall | Benignos marcados |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
        for n, r in evals.items():
            g, s = r["global"], r["servidores"]
            t.append(f"| {n} | {g['tp']} | {g['fp']} | {g['fn']} | {_f(g['precision'])} | {_f(g['recall'])} | "
                     f"{s['benignos_marcados']} de {s['benignos']} |")
        esperados = next(iter(evals.values()))["esperados"]
        t += ["", "## Qué detecta cada técnica", "", "| Servidor | Categoría esperada | " +
              " | ".join(evals) + " |", "| --- | --- | " + " | ".join("---" for _ in evals) + " |"]
        for srv, cat in sorted(esperados):
            t.append(f"| {srv} | {cat} | " + " | ".join("✓" if (srv, cat) in r["global"]["_tp"] else "·"
                                                         for r in evals.values()) + " |")
        fps = {n: sorted(r["global"]["_fp"]) for n, r in evals.items()}
        if any(fps.values()):
            t += ["", "Falsos positivos:", ""] + [f"- {n}: {', '.join(f'{s} ({c})' for s, c in v)}"
                                                  for n, v in fps.items() if v]
        resultado["metricas"] = {n: {k: v for k, v in r["global"].items() if not k.startswith("_")}
                                 for n, r in evals.items()}
        resultado["deteccion"] = {f"{s}/{c}": {n: (s, c) in r["global"]["_tp"] for n, r in evals.items()}
                                  for s, c in sorted(esperados)}
    else:
        pares = {n: {(h["servidor"], h["categoria"]) for h in hs} for n, hs in tecnicas.items()}
        srv = {n: {s for s, _ in p} for n, p in pares.items()}
        t += ["## Hallazgos sin ground truth", "",
              "Son hallazgos, no tool poisoning confirmado: hay que revisarlos a mano (revision_b.csv).", "",
              "| Técnica | Hallazgos | Servidores marcados |", "| --- | --- | --- |"]
        for n, hs in tecnicas.items():
            t.append(f"| {n} | {len(hs)} | {len(srv[n])} |")
        if len(pares) == 2:
            h_, l_ = srv["heuristicas"], srv["clasificador_llm"]
            t += ["", f"Servidores marcados por las dos técnicas: {len(h_ & l_)}; solo heurísticas: {len(h_ - l_)}; "
                      f"solo LLM: {len(l_ - h_)}."]
            resultado["acuerdo_servidores"] = {"ambas": len(h_ & l_), "solo_heuristicas": len(h_ - l_),
                                               "solo_llm": len(l_ - h_)}
        resultado["hallazgos"] = {n: len(hs) for n, hs in tecnicas.items()}
        with (out / "revision_b.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["id", "servidor", "tecnica", "categoria", "severidad", "regla", "ubicacion", "evidencia",
                        "veredicto", "nota"])
            for i, h in enumerate([h for hs in tecnicas.values() for h in hs], 1):
                w.writerow([i, h["servidor"], h["analizador"], h["categoria"], h["severidad"], h["regla"],
                            h["ubicacion"], h["evidencia"], "", ""])

    if llm:
        t += ["", "## Costo y consistencia del clasificador LLM", "",
              f"- Modelo: {llm['modelo']} ({llm['proveedor']}), prompt {llm['prompt']}, temperatura {llm['temperatura']}",
              f"- Repeticiones por servidor: {llm['repeticiones']} (los hallazgos se deciden por mayoría)",
              f"- Llamadas: {llm['llamadas']} ({llm['desde_cache']} desde caché)",
              f"- Tokens: {llm['tokens_entrada']} de entrada y {llm['tokens_salida']} de salida",
              f"- Costo total: {llm['costo_total_usd']} USD; por servidor y repetición: {llm['costo_por_servidor_usd']} USD",
              f"- Tiempo medio por llamada: {llm['segundos_por_llamada']} s",
              f"- Consistencia: {_f(llm['consistencia_herramientas'])} de las herramientas y "
              f"{_f(llm['consistencia_servidores'])} de los servidores reciben el mismo veredicto en todas las repeticiones",
              f"- Errores: {len(llm['errores'])}"]
        resultado["llm"] = {k: v for k, v in llm.items() if k != "hallazgos"}
    t += ["", "## Heurísticas", "", f"- Tiempo total: {seg_h:.2f} s ({seg_h / max(con_herr, 1) * 1000:.1f} ms por servidor); "
          "costo 0 y resultado idéntico en cada corrida."]

    (out / "comparacion.md").write_text("\n".join(t) + "\n", encoding="utf-8", newline="\n")
    escribir("comparacion.json", resultado)
    print(f"\nListo en {out}. Abre comparacion.md.")


if __name__ == "__main__":
    main()
