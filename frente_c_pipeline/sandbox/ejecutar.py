#!/usr/bin/env python3
"""Ejecuta cada servidor del corpus en un contenedor aislado y guarda un .json por servidor.

Desde la raíz del repositorio (requiere Docker):
    python frente_c_pipeline/sandbox/ejecutar.py corpus/banco_de_pruebas resultados/dinamico

Solo para el banco de pruebas: el cliente arranca src/index.ts. No ejecutar el corpus
real con esto (el alcance comprometido no ejecuta código de terceros).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
IMAGEN = "mcpscan-sandbox"


def main() -> None:
    if shutil.which("docker") is None:
        sys.exit("Docker no está instalado o no está en el PATH.")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        sys.exit("Docker está instalado pero el motor no está corriendo. Abre Docker Desktop, "
                 "espera a que diga 'Engine running' y vuelve a intentar.")
    corpus, salida = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    salida.mkdir(parents=True, exist_ok=True)
    print("Construyendo la imagen (la primera vez descarga node:22-slim y tarda un par de minutos)...")
    b = subprocess.run(["docker", "build", "--progress=plain", "-t", IMAGEN, str(AQUI)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if b.returncode != 0:
        print("\n".join((b.stdout + b.stderr).splitlines()[-40:]), file=sys.stderr)
        sys.exit("\nFalló la construcción de la imagen. Copia el error de arriba.")
    for d in sorted(p for p in corpus.iterdir() if (p / "manifest.json").exists()):
        print(f"-> {d.name}")
        cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--read-only", "--tmpfs", "/tmp:rw,size=16m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "128", "--memory", "256m", "--cpus", "0.5",
            "-v", f"{(d / 'codigo').resolve()}:/sandbox/servidores/{d.name}/codigo:ro",
            IMAGEN, f"/sandbox/servidores/{d.name}/codigo",
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
            texto = r.stdout or json.dumps({"servidor": d.name, "hallazgos": [], "error": r.stderr[:500]})
        except subprocess.TimeoutExpired:
            texto = json.dumps({"servidor": d.name, "hallazgos": [], "error": "tiempo excedido"})
        (salida / f"{d.name}.json").write_text(texto, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
