#!/usr/bin/env python3
"""Corrida completa para el informe: desarrollo, validación y servidores reales en un solo paso.

Desde la raíz del repositorio:
    python -m frente_c_pipeline.corrida_informe [--sandbox] [--sin-validacion] [--sin-reales]

Deja todo en resultados/informe/<fecha_hora>/ (ignorado por git):
    resumen.md                 qué se corrió, con qué versión, errores y advertencias
    tablas.md                  tablas listas para el informe (desarrollo vs validación, matrices, reales)
    tabla_resumen.csv          las mismas cifras en CSV, para gráficos
    tabla_categorias.csv
    hallazgos_<conjunto>.json  hallazgos crudos de cada conjunto
    metricas_<conjunto>.json   precisión, recall y matriz (desarrollo y validación)
    reporte_real_anonimo.md    riesgo por servidor real, con nombres S01, S02... (este sí va al informe)
    revision_manual.csv        hallazgos reales para revisar a mano (PRIVADO: tiene nombres reales)
    mapa_anonimizacion.csv     S01 -> nombre real (PRIVADO)

El sandbox solo se usa con el banco de desarrollo y la validación, nunca con los servidores reales.
"""
import argparse
import csv
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from comun.formatos import CATEGORIAS
from frente_c_pipeline.evaluar import _corto, evaluar, limpiar
from frente_c_pipeline.pipeline import ANALIZADORES, correr, servidores
from frente_c_pipeline.reporte import construir

CSV_OPCIONES = {"delimiter": ";"}  # Excel en español separa columnas con ';'


def _escribir_json(ruta: Path, datos) -> None:
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def _escribir_csv(ruta: Path, encabezado: list[str], filas: list[list]) -> None:
    # utf-8-sig para que Excel muestre bien los acentos.
    with ruta.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, **CSV_OPCIONES)
        w.writerow(encabezado)
        w.writerows(filas)


def _pct(x) -> str:
    return "—" if x is None else f"{x:.2f}".replace(".", ",")


def _version_git() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
        sucio = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip() + (" (con cambios sin commitear)" if sucio.stdout.strip() else "")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "desconocida"


NOMBRE = {"desarrollo": "Desarrollo", "validacion": "Validación"}


def _obt(r: dict, a: str) -> set:
    m = r["por_analizador"].get(a)
    return m["_obt"] if m else set()


def _fp(r: dict, a: str) -> int:
    m = r["por_analizador"].get(a)
    return m["falsos_positivos"] if m else 0


def _version_semgrep() -> str:
    try:
        from frente_a_estatico.analizador import _buscar_semgrep
        exe = _buscar_semgrep()
        if exe:
            r = subprocess.run([exe, "--version", "--disable-version-check"], capture_output=True, text=True, timeout=60)
            return r.stdout.strip().splitlines()[0] if r.stdout.strip() else "desconocida"
    except Exception:
        pass
    return "no encontrada"


def _matriz(r: dict, ans: list[str]) -> list[str]:
    """Una columna por cada analizador que se corrió, aunque no haya encontrado nada."""
    lineas = ["| Servidor | Categoría | " + " | ".join(_corto(a) for a in ans) + " |",
              "| --- | --- | " + " | ".join("---" for _ in ans) + " |"]
    for srv, cat in sorted(r["esperados"]):
        marcas = " | ".join("✓" if (srv, cat) in _obt(r, a) else "·" for a in ans)
        lineas.append(f"| {srv} | {cat} | {marcas} |")
    lineas.append("| **Falsos positivos** | | " + " | ".join(str(_fp(r, a)) for a in ans) + " |")
    return lineas


def _dinamico(nombre: str, corpus: Path, args, out: Path, avisos: list[str]) -> Path | None:
    """Carpeta con resultados del sandbox para ese conjunto, o None."""
    if args.sandbox:
        from frente_c_pipeline.sandbox.ejecutar import ejecutar
        destino = out / f"dinamico_{nombre}"
        ejecutar(corpus, destino)
        return destino
    # Mismas carpetas que usan los comandos de frente_c_pipeline/README.md.
    previa = Path("resultados") / {"desarrollo": "dinamico", "validacion": "dinamico_val"}[nombre]
    if any(previa.glob("*.json")):
        fecha = datetime.fromtimestamp(max(f.stat().st_mtime for f in previa.glob("*.json")))
        avisos.append(f"{nombre}: se usaron resultados del sandbox ya existentes en {previa} "
                      f"(del {fecha:%d-%m-%Y %H:%M}). Usa --sandbox para regenerarlos.")
        return previa
    avisos.append(f"{nombre}: sin sandbox (no hay resultados en {previa}; usa --sandbox para incluirlo).")
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--salida", default="resultados/informe")
    ap.add_argument("--desarrollo", default="corpus/banco_de_pruebas")
    ap.add_argument("--validacion", default="corpus/validacion")
    ap.add_argument("--reales", default="corpus/real")
    ap.add_argument("--analizadores", nargs="+", default=ANALIZADORES)
    ap.add_argument("--sandbox", action="store_true",
                    help="corre el sandbox (requiere Docker) sobre desarrollo y validación")
    ap.add_argument("--sin-validacion", action="store_true")
    ap.add_argument("--sin-reales", action="store_true")
    args = ap.parse_args()

    inicio = time.time()
    out = Path(args.salida) / datetime.now().strftime("%Y-%m-%d_%H%M")
    out.mkdir(parents=True, exist_ok=True)
    avisos: list[str] = []

    if args.sandbox:
        from frente_c_pipeline.sandbox.ejecutar import DockerNoDisponible, preparar_docker
        try:
            preparar_docker()
        except DockerNoDisponible as e:
            sys.exit(str(e))

    conjuntos = [("desarrollo", Path(args.desarrollo))]
    if not args.sin_validacion:
        if (Path(args.validacion) / "ground_truth.json").exists():
            conjuntos.append(("validacion", Path(args.validacion)))
        else:
            avisos.append(f"validación: no existe {args.validacion}. Genérala con "
                          "python -m frente_c_pipeline.generar_banco corpus/validacion --conjunto validacion")
    reales = Path(args.reales)
    hay_reales = not args.sin_reales and reales.is_dir() and servidores(reales)
    if not args.sin_reales and not hay_reales:
        avisos.append(f"reales: no hay servidores en {reales}. Descárgalos con "
                      "python frente_a_estatico/recolectar.py corpus/real --desde-muestra corpus/muestra_real.json")

    evals, errores_tot = {}, {}
    corridos = list(args.analizadores)  # columnas de las tablas
    for nombre, corpus in conjuntos:
        print(f"\n=== {nombre} ({corpus})")
        din = _dinamico(nombre, corpus, args, out, avisos)
        if din and "sandbox" not in corridos:
            corridos.append("sandbox")
        hall, errores = correr(corpus, args.analizadores, din)
        gt = json.loads((corpus / "ground_truth.json").read_text(encoding="utf-8"))
        r = evaluar(gt, hall)
        evals[nombre], errores_tot[nombre] = r, errores
        _escribir_json(out / f"hallazgos_{nombre}.json", hall)
        _escribir_json(out / f"metricas_{nombre}.json", limpiar(r))
        g = r["global"]
        print(f"    precisión {_pct(g['precision'])}  recall {_pct(g['recall'])}  "
              f"({g['tp']} de {g['tp'] + g['fn']})  errores: {len(errores)}")

    filas_reales, hall_real = [], []
    if hay_reales:
        print(f"\n=== reales ({reales}, {len(servidores(reales))} servidores; sin sandbox)")
        hall_real, errores = correr(reales, args.analizadores)
        errores_tot["reales"] = errores
        _escribir_json(out / "hallazgos_reales.json", hall_real)
        filas_reales = construir(hall_real, [p.name for p in servidores(reales)])
        mapa = []
        for i, f in enumerate(filas_reales, 1):
            mapa.append([f"S{i:02d}", f["servidor"]])
            f["anonimo"] = f"S{i:02d}"
        _escribir_csv(out / "mapa_anonimizacion.csv", ["anonimo", "servidor"], mapa)
        anon = {real: an for an, real in mapa}
        con = [f for f in filas_reales if f["puntaje"]]
        lineas = ["# Reporte de riesgo (servidores reales, anonimizado)", "",
                  f"{len(con)} de {len(filas_reales)} servidores con al menos un hallazgo.", "",
                  "| Servidor | Puntaje | Severidad máxima | Categorías |", "| --- | --- | --- | --- |"]
        lineas += [f"| {f['anonimo']} | {f['puntaje']} | {f['severidad_maxima']} | {', '.join(f['categorias'])} |"
                   for f in con]
        (out / "reporte_real_anonimo.md").write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
        _escribir_csv(out / "revision_manual.csv",
                      ["id", "anonimo", "servidor", "categoria", "regla", "severidad", "ubicacion",
                       "evidencia", "analizador", "veredicto", "nota"],
                      [[i, anon[h["servidor"]], h["servidor"], h["categoria"], h["regla"], h["severidad"],
                        h["ubicacion"], h["evidencia"], h.get("analizador", ""), "", ""]
                       for i, h in enumerate(hall_real, 1)])
        print(f"    {len(hall_real)} hallazgos en {len(con)} servidores  errores: {len(errores)}")

    # ---------------------------------------------------------------- tablas
    t = ["# Tablas para el informe", "", f"Corrida del {datetime.now():%d-%m-%Y %H:%M}, versión {_version_git()}.", ""]
    t += ["## Desarrollo frente a validación", "",
          "| Conjunto | Servidores | Precisión | Recall | Problemas detectados | Maliciosos detectados | Benignos marcados |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    resumen_csv = []
    for nombre, r in evals.items():
        g, s = r["global"], r["servidores"]
        n = s["maliciosos"] + s["benignos"]
        t.append(f"| {NOMBRE[nombre]} | {n} | {_pct(g['precision'])} | {_pct(g['recall'])} | {g['tp']} de {g['tp'] + g['fn']} | "
                 f"{s['maliciosos_detectados']} de {s['maliciosos']} | {s['benignos_marcados']} de {s['benignos']} |")
        resumen_csv.append([nombre, n, g["precision"], g["recall"], g["tp"], g["fp"], g["fn"],
                            s["maliciosos_detectados"], s["maliciosos"], s["benignos_marcados"], s["benignos"]])

    t += ["", "## Qué detecta cada técnica", "",
          "Aciertos (problemas esperados que encontró) y falsos positivos de cada analizador.", "",
          "| Analizador | " + " | ".join(f"{NOMBRE[n]}: aciertos | {NOMBRE[n]}: falsos+" for n in evals) + " |",
          "| --- | " + " | ".join("--- | ---" for _ in evals) + " |"]
    for a in corridos:
        celdas = [f"{len(_obt(r, a) & r['esperados'])} | {_fp(r, a)}" for r in evals.values()]
        t.append(f"| {_corto(a)} | " + " | ".join(celdas) + " |")

    t += ["", "## Recall por categoría", "",
          "| Categoría | Frente | " + " | ".join(NOMBRE[n] for n in evals) + " |", "| --- | --- | " + " | ".join("---" for _ in evals) + " |"]
    cat_csv = []
    for cat, (frente, _) in CATEGORIAS.items():
        valores = []
        for nombre, r in evals.items():
            m = r["por_categoria"].get(cat)
            valores.append(f"{m['tp']} de {m['tp'] + m['fn']}" if m and (m["tp"] + m["fn"]) else "—")
            cat_csv.append([cat, frente, nombre, m["tp"] if m else 0, m["fn"] if m else 0, m["fp"] if m else 0])
        t.append(f"| {cat} | {frente} | " + " | ".join(valores) + " |")

    for nombre, r in evals.items():
        t += ["", f"## Matriz de detección: {NOMBRE[nombre]}", ""] + _matriz(r, corridos)

    if hay_reales:
        por_cat = Counter((h["categoria"], h["severidad"]) for h in hall_real)
        t += ["", "## Servidores reales", "",
              f"{sum(1 for f in filas_reales if f['puntaje'])} de {len(filas_reales)} servidores con al menos un hallazgo; "
              f"{len(hall_real)} hallazgos en total. Sin revisión manual: son hallazgos, no vulnerabilidades confirmadas.", "",
              "| Categoría | Severidad | Hallazgos | Servidores |", "| --- | --- | --- | --- |"]
        for (cat, sev), n in sorted(por_cat.items()):
            srv = len({h["servidor"] for h in hall_real if h["categoria"] == cat and h["severidad"] == sev})
            t.append(f"| {cat} | {sev} | {n} | {srv} |")
    (out / "tablas.md").write_text("\n".join(t) + "\n", encoding="utf-8", newline="\n")
    _escribir_csv(out / "tabla_resumen.csv",
                  ["conjunto", "servidores", "precision", "recall", "aciertos", "falsos_positivos", "falsos_negativos",
                   "maliciosos_detectados", "maliciosos", "benignos_marcados", "benignos"], resumen_csv)
    _escribir_csv(out / "tabla_categorias.csv",
                  ["categoria", "frente", "conjunto", "aciertos", "falsos_negativos", "falsos_positivos"], cat_csv)

    # --------------------------------------------------------------- resumen
    n_err = sum(len(e) for e in errores_tot.values())
    if n_err:
        avisos.insert(0, f"HUBO {n_err} ERRORES de analizadores: los resultados están incompletos. "
                         "Detalle en errores_<conjunto>.json.")
    for nombre, e in errores_tot.items():
        if e:
            _escribir_json(out / f"errores_{nombre}.json", e)
    if "validacion" in evals:
        avisos.append("Las tablas incluyen el conjunto de validación: si se ajustan reglas o heurísticas "
                      "mirando estos resultados, deja de ser un conjunto ciego.")
    if hay_reales:
        avisos.append("revision_manual.csv y mapa_anonimizacion.csv tienen nombres reales: no van al informe ni a git. "
                      "Al informe va reporte_real_anonimo.md.")
    r_md = ["# Resumen de la corrida", "",
            f"- Fecha: {datetime.now():%d-%m-%Y %H:%M}",
            f"- Versión del código: {_version_git()}",
            f"- Versión de Semgrep: {_version_semgrep()}",
            f"- Analizadores: {', '.join(args.analizadores)}",
            f"- Conjuntos: {', '.join(evals) + (', reales' if hay_reales else '')}",
            f"- Duración: {round(time.time() - inicio)} segundos",
            f"- Errores de analizadores: {n_err}", "", "## Avisos", ""] + [f"- {a}" for a in avisos]
    (out / "resumen.md").write_text("\n".join(r_md) + "\n", encoding="utf-8", newline="\n")

    print(f"\nListo en {out}. Abre tablas.md y resumen.md.")
    for a in avisos:
        print(f"  ! {a}")


if __name__ == "__main__":
    main()
