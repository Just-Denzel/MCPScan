"""La corrida para el informe y la revisión manual."""
import csv
import subprocess
import sys
from pathlib import Path

from frente_c_pipeline.revision import _normalizar, leer, resumir

RAIZ = Path(__file__).resolve().parent.parent


def test_corrida_informe_genera_las_tablas(tmp_path):
    # Solo el analizador B (no necesita Semgrep) y solo desarrollo, para que sea rápido.
    r = subprocess.run(
        [sys.executable, "-m", "frente_c_pipeline.corrida_informe", "--salida", str(tmp_path),
         "--analizadores", "frente_b_descripciones.analizador", "--sin-validacion", "--sin-reales"],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    (carpeta,) = tmp_path.iterdir()
    for f in ("tablas.md", "resumen.md", "tabla_resumen.csv", "metricas_desarrollo.json"):
        assert (carpeta / f).exists(), f
    tablas = (carpeta / "tablas.md").read_text(encoding="utf-8")
    assert "Matriz de detección: Desarrollo" in tablas
    assert "| poison-instruccion-oculta | tool-poisoning-instruccion | ✓" in tablas


def test_revision_normaliza_veredictos():
    assert _normalizar("Verdadero") == "verdadero"
    assert _normalizar(" sí ") == "verdadero"
    assert _normalizar("F") == "falso"
    assert _normalizar("") == "pendiente"
    assert _normalizar("quizás") == "invalido"


def test_revision_calcula_la_precision(tmp_path):
    ruta = tmp_path / "revision_manual.csv"
    with ruta.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "categoria", "regla", "veredicto"])
        w.writerows([[1, "ejecucion-de-comando", "r", "verdadero"],
                     [2, "ejecucion-de-comando", "r", "falso"],
                     [3, "ejecucion-de-comando", "r", "falso"],
                     [4, "script-instalacion", "s", "dudoso"],
                     [5, "script-instalacion", "s", ""]])
    r = resumir(leer(ruta))
    assert r["total"] == {"verdadero": 1, "falso": 2, "dudoso": 1, "pendiente": 1, "invalido": 0}
    assert r["por_categoria"]["ejecucion-de-comando"]["falso"] == 2
