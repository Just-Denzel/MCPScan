"""Casos pequeños para las reglas de Semgrep del frente A (tests/casos_reglas/).

Cada caso marca en un comentario si la línea DEBE o NO debe detectarse. Si se cambia una
regla y este test falla, se rompió un caso que antes funcionaba.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from frente_a_estatico.analizador import REGLAS, _buscar_semgrep

CASOS = Path(__file__).resolve().parent / "casos_reglas"

# (archivo, línea, regla) que deben aparecer
ESPERADOS = {
    ("a_tool_destructurado.ts", 3, "mcp-argumento-a-shell"),
    ("b_tool_args.ts", 4, "mcp-argumento-a-shell"),
    ("c_request_handler_wrapper.ts", 11, "mcp-argumento-a-shell"),
    ("d_spawn_shell.js", 3, "mcp-argumento-a-shell"),
    ("g_rutas.js", 2, "ruta-archivo-sensible-construida"),
    ("g_rutas.js", 3, "ruta-archivo-sensible-construida"),
}
# (archivo, línea) donde no debe haber NINGÚN hallazgo de severidad alta
SIN_ALTA = {
    ("a_tool_destructurado.ts", 4), ("b_tool_args.ts", 7), ("c_request_handler_wrapper.ts", 12),
    ("d_spawn_shell.js", 4), ("d_spawn_shell.js", 5),
    ("e_wrapper_inocuo.ts", 5), ("e_wrapper_inocuo.ts", 6),
    ("f_regex_exec.ts", 2), ("f_regex_exec.ts", 3), ("f_regex_exec.ts", 6),
    ("g_rutas.js", 4), ("g_rutas.js", 5),
}


@pytest.mark.skipif(_buscar_semgrep() is None, reason="Semgrep no instalado")
def test_casos_de_las_reglas():
    # Lista explícita de archivos, igual que el analizador: algunas versiones de Semgrep
    # (vista en Windows con la 1.184) no analizan nada si se les pasa una carpeta llamada tests/.
    archivos = sorted(str(f) for f in CASOS.iterdir() if f.is_file())
    r = subprocess.run([_buscar_semgrep(), "--metrics=off", "--disable-version-check", "--quiet", "--json",
                        "--no-git-ignore", "-f", str(REGLAS), *archivos],
                       capture_output=True, text=True, encoding="utf-8")
    datos = json.loads(r.stdout)
    assert datos["results"], (f"Semgrep no devolvió resultados (código {r.returncode}). "
                              f"Errores: {datos.get('errors')} | stderr: {r.stderr[-500:]}")
    hallados = {(Path(x["path"]).name, x["start"]["line"], x["check_id"].split(".")[-1]) for x in datos["results"]}
    altas = {(Path(x["path"]).name, x["start"]["line"]) for x in datos["results"] if x["extra"]["severity"] == "ERROR"}
    assert ESPERADOS <= hallados, f"faltan: {ESPERADOS - hallados}"
    assert not (SIN_ALTA & altas), f"severidad alta donde no corresponde: {SIN_ALTA & altas}"
