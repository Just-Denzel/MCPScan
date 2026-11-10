"""El banco de pruebas versionado coincide con su generador y está completo."""
import filecmp
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "corpus/banco_de_pruebas"


def _iguales(a: Path, b: Path) -> list[str]:
    cmp = filecmp.dircmp(a, b)
    dif = [str(a / f) for f in cmp.left_only + cmp.right_only + cmp.diff_files + cmp.funny_files]
    for sub in cmp.common_dirs:
        dif += _iguales(a / sub, b / sub)
    return dif


def test_generador_reproduce_el_banco(tmp_path):
    subprocess.run([sys.executable, "-m", "frente_c_pipeline.generar_banco", str(tmp_path / "b")],
                   cwd=RAIZ, check=True, capture_output=True)
    # Si falla: alguien editó el banco a mano. Editar generar_banco.py y regenerar.
    assert _iguales(tmp_path / "b", BANCO) == []


def test_cada_servidor_tiene_el_formato_de_corpus():
    gt = json.loads((BANCO / "ground_truth.json").read_text(encoding="utf-8"))
    for s in gt["servidores"]:
        d = BANCO / s["servidor"]
        for f in ("manifest.json", "herramientas.json", "codigo/package.json", "codigo/src/index.ts"):
            assert (d / f).exists(), f"falta {d / f}"
        for h in s["hallazgos_esperados"]:
            lineas = (d / h["archivo"]).read_text(encoding="utf-8").splitlines()
            assert 1 <= h["linea"] <= len(lineas)


def test_hay_benignos_y_maliciosos():
    gt = json.loads((BANCO / "ground_truth.json").read_text(encoding="utf-8"))
    etiquetas = [s["etiqueta"] for s in gt["servidores"]]
    assert etiquetas.count("benigno") >= 5 and etiquetas.count("malicioso") >= 8
