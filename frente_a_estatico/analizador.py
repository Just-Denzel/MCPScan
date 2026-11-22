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
from frente_a_estatico.detectores_python import analizar_python

REGLAS = Path(__file__).resolve().parent / "reglas"
SEVERIDAD = {"ERROR": "alta", "WARNING": "media", "INFO": "baja"}
EXTENSIONES_JS = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}

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


def _archivos_codigo(codigo: Path) -> list[str]:
    """Lista archivos JS/TS explícitos para evitar que .semgrepignore salte *.min.js."""
    archivos = []
    for p in sorted(codigo.rglob("*")):
        if not p.is_file():
            continue
        if "node_modules" in p.parts or ".git" in p.parts:
            continue
        if p.name.endswith(".d.ts"):
            continue
        if p.suffix.lower() in EXTENSIONES_JS:
            archivos.append(str(p))
    return archivos

def _extraer_evidencia(archivo: Path, linea: int, col: int = 1) -> str:
    """Lee la línea real desde el archivo cuando Semgrep devuelve 'requires login'."""
    try:
        lineas = archivo.read_text(encoding="utf-8", errors="ignore").splitlines()
        if 1 <= linea <= len(lineas):
            texto = lineas[linea - 1].strip()
            if len(texto) > 250 and col > 1:
                ini = max(0, col - 40)
                texto = texto[ini:ini + 250]
            return texto
    except OSError:
        pass
    return ""

def _semgrep(dir_servidor: Path) -> list[dict]:
    codigo = dir_servidor / "codigo"
    if not codigo.exists():
        return []
    objetivos = _archivos_codigo(codigo)
    if not objetivos:
        return []
    semgrep = _buscar_semgrep()
    if semgrep is None:
        raise RuntimeError(
            f"No se encontró Semgrep para este Python ({sys.executable}). "
            "Instálalo con: python -m pip install semgrep  (o activa el entorno virtual donde lo instalaste)")

    base = dir_servidor.resolve()
    salida = []
    vistos = set()

    # Lotes de 100 archivos para no exceder límites de línea de comandos en Windows
    for i in range(0, len(objetivos), 100):
        lote = objetivos[i:i + 100]
        r = subprocess.run(
            [semgrep, "--metrics=off", "--disable-version-check", "--quiet",
             "--no-git-ignore", "--json", "-f", str(REGLAS), *lote],
            capture_output=True, text=True,
        )
        # Sin esta comprobación, un Semgrep que falla parece "0 hallazgos" (falso negativo silencioso).
        if r.returncode not in (0, 1) or not r.stdout.strip():
            raise RuntimeError(f"Semgrep falló (código {r.returncode}): {r.stderr.strip()[-300:]}")
        datos = json.loads(r.stdout)
        for res in datos.get("results", []):
            regla = res["check_id"].split(".")[-1]
            categoria = res["extra"].get("metadata", {}).get("categoria", regla)
            ruta = Path(res["path"]).resolve().relative_to(base).as_posix()
            ubicacion = f"{ruta}:{res['start']['line']}"
            clave = (categoria, regla, ubicacion)
            if clave in vistos:
                continue
            vistos.add(clave)

            evidencia = res["extra"].get("lines", "").strip()
            if not evidencia or evidencia.lower() == "requires login":
                evidencia = _extraer_evidencia(
                    Path(res["path"]),
                    res["start"]["line"],
                    res["start"].get("col", 1),
                ) or res["extra"].get("message", regla)

            salida.append(hallazgo(
                servidor=dir_servidor.name,
                categoria=categoria,
                regla=regla,
                severidad=SEVERIDAD.get(res["extra"].get("severity", ""), "media"),
                evidencia=evidencia,
                ubicacion=ubicacion,
            ))
    return salida


def analizar(dir_servidor: Path) -> list[dict]:
    return _semgrep(dir_servidor) + analizar_python(dir_servidor)
