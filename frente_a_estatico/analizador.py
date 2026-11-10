"""Frente A: análisis estático del código de cada servidor.

Contrato con el pipeline: analizar(dir_servidor) -> lista de hallazgos (ver docs/formatos.md).
Esta versión inicial solo corre Semgrep con las reglas de reglas/. Aquí se agregan
también detectores propios en Python (package.json, dependencias, etc.).
"""
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from comun.formatos import hallazgo

REGLAS = Path(__file__).resolve().parent / "reglas"
SEVERIDAD = {"ERROR": "alta", "WARNING": "media", "INFO": "baja"}


def _buscar_semgrep() -> str | None:
    """Semgrep en el PATH o, si no, en la carpeta de scripts de este Python.

    En Windows, pip suele instalarlo en una carpeta Scripts que no está en el PATH.
    """
    if encontrado := shutil.which("semgrep"):
        return encontrado
    nombre = "semgrep.exe" if os.name == "nt" else "semgrep"
    carpetas = {Path(sys.executable).parent, Path(sys.executable).parent / "Scripts",
                Path(sysconfig.get_path("scripts"))}
    try:
        carpetas.add(Path(sysconfig.get_path("scripts", f"{os.name}_user")))
    except KeyError:
        pass
    for c in carpetas:
        if (c / nombre).is_file():
            return str(c / nombre)
    return None


def _semgrep(dir_servidor: Path) -> list[dict]:
    codigo = dir_servidor / "codigo"
    if not codigo.exists():
        return []
    semgrep = _buscar_semgrep()
    if semgrep is None:
        raise RuntimeError(
            f"No se encontró Semgrep para este Python ({sys.executable}). "
            "Instálalo con: python -m pip install semgrep  (o activa el entorno virtual donde lo instalaste)")
    r = subprocess.run(
        [semgrep, "--metrics=off", "--disable-version-check", "--quiet", "--json",
         "-f", str(REGLAS), str(codigo)],
        capture_output=True, text=True,
    )
    # Sin esta comprobación, un Semgrep que falla parece "0 hallazgos" (falso negativo silencioso).
    if r.returncode not in (0, 1) or not r.stdout.strip():
        raise RuntimeError(f"Semgrep falló (código {r.returncode}): {r.stderr.strip()[-300:]}")
    datos = json.loads(r.stdout)
    base = dir_servidor.resolve()
    salida = []
    for res in datos.get("results", []):
        regla = res["check_id"].split(".")[-1]
        # Cada regla declara su categoría en metadata.categoria (ver reglas/*.yml).
        categoria = res["extra"].get("metadata", {}).get("categoria", regla)
        ruta = Path(res["path"]).resolve().relative_to(base).as_posix()
        salida.append(hallazgo(
            servidor=dir_servidor.name,
            categoria=categoria,
            regla=regla,
            severidad=SEVERIDAD.get(res["extra"].get("severity", ""), "media"),
            evidencia=res["extra"].get("lines", ""),
            ubicacion=f"{ruta}:{res['start']['line']}",
        ))
    return salida


def analizar(dir_servidor: Path) -> list[dict]:
    hallazgos = _semgrep(dir_servidor)
    # TODO (frente A): secretos, dependencias sospechosas, scripts de instalación.
    return hallazgos
