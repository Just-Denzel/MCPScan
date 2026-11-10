#!/usr/bin/env python3
"""Descarga N servidores MCP públicos de npm al formato de corpus, SIN ejecutar nada.

Uso (desde la raíz): python frente_a_estatico/recolectar.py corpus/real [--n 100] [--semilla 1]
Requiere Python 3.12 o superior.

- Lista servidores del registry oficial de MCP (solo la última versión, activos, con paquete npm).
- Para no sesgar hacia la "A", toma una página desde muchos puntos de partida (cursores).
- Descarga el .tgz desde el registry de npm, verifica su integridad y lo extrae con
  tarfile (filter="data": bloquea rutas absolutas, '..' y enlaces que escapen).
- Nunca ejecuta npm install, scripts ni código del paquete.
"""
import argparse
import base64
import hashlib
import io
import json
import random
import re
import shutil
import tarfile
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

REGISTRO = "https://registry.modelcontextprotocol.io/v0/servers"
NPM = "https://registry.npmjs.org"
META = "io.modelcontextprotocol.registry/official"
MAX_TGZ = 20 * 1024 * 1024  # 20 MB comprimido
MAX_EXTRAIDO = 200 * 1024 * 1024  # 200 MB descomprimido (evita bombas de descompresión)
CURSORES = (["", "ac.", "ai.", "app.", "co.", "com.a", "com.c", "com.m", "com.s", "dev.", "eu.", "io.",
             "me.", "net.", "org."] + [f"io.github.{c}" for c in "abcdefghijklmnopqrstuvwxyz"])


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "mcpscan-curso/0.1"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def candidatos() -> dict:
    """Devuelve {paquete_npm: info} con la última versión activa de cada servidor."""
    salida = {}
    for cur in CURSORES:
        url = f"{REGISTRO}?limit=100" + (f"&cursor={urllib.parse.quote(cur)}" if cur else "")
        try:
            pagina = get_json(url)
        except Exception as e:  # una página que falla no detiene el resto
            print(f"  aviso: cursor {cur!r} falló ({e})")
            continue
        for e in pagina.get("servers", []):
            s, m = e["server"], e["_meta"].get(META, {})
            if not m.get("isLatest") or m.get("status") != "active":
                continue
            for p in s.get("packages", []):
                if p.get("registryType") == "npm" and p.get("identifier") and p.get("version"):
                    salida.setdefault(p["identifier"], {
                        "paquete": p["identifier"], "version": p["version"],
                        "nombre_registro": s["name"],
                        "repositorio": (s.get("repository") or {}).get("url"),
                    })
    return salida


def descargar(info: dict) -> tuple[bytes, str]:
    """Baja el tarball y verifica su integridad contra los metadatos de npm."""
    nombre = urllib.parse.quote(info["paquete"], safe="@")
    meta = get_json(f"{NPM}/{nombre}/{urllib.parse.quote(info['version'])}")
    dist = meta["dist"]
    req = urllib.request.Request(dist["tarball"], headers={"User-Agent": "mcpscan-curso/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        datos = r.read(MAX_TGZ + 1)
    if len(datos) > MAX_TGZ:
        raise ValueError("tarball mayor a 20 MB")
    integ = dist.get("integrity", "")
    if integ.startswith("sha512-"):
        if base64.b64encode(hashlib.sha512(datos).digest()).decode() != integ[7:]:
            raise ValueError("integridad sha512 no coincide")
    elif dist.get("shasum") and hashlib.sha1(datos).hexdigest() != dist["shasum"]:
        raise ValueError("shasum no coincide")
    return datos, integ or dist.get("shasum", "")


def extraer(datos: bytes, destino: Path) -> None:
    destino.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(datos), mode="r:gz") as tf:
        miembros = tf.getmembers()
        if sum(m.size for m in miembros) > MAX_EXTRAIDO:
            raise ValueError("contenido descomprimido mayor a 200 MB")
        for m in miembros:  # npm empaqueta bajo "package/" (a veces con otro nombre de carpeta)
            m.name = re.sub(r"^[^/]+/", "", m.name, count=1)
        tf.extractall(destino, members=[m for m in miembros if m.name], filter="data")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("salida")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--semilla", type=int, default=1)
    a = ap.parse_args()
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)

    print("Listando servidores del registry oficial...")
    cand = candidatos()
    print(f"{len(cand)} paquetes npm candidatos")
    claves = sorted(cand)
    random.Random(a.semilla).shuffle(claves)

    ok, fallos = 0, []
    for k in claves:
        if ok >= a.n:
            break
        info = cand[k]
        carpeta = salida / re.sub(r"[^a-zA-Z0-9._-]", "__", info["paquete"].lstrip("@"))
        if (carpeta / "manifest.json").exists():  # ya descargado en una corrida anterior
            ok += 1
            continue
        if carpeta.exists():  # quedó a medias (corrida interrumpida): se rehace
            shutil.rmtree(carpeta)
        try:
            datos, integ = descargar(info)
            extraer(datos, carpeta / "codigo")
        except Exception as e:
            fallos.append((info["paquete"], str(e)))
            if carpeta.exists():
                shutil.rmtree(carpeta)
            continue
        (carpeta / "manifest.json").write_text(json.dumps({
            "nombre": carpeta.name, "fuente": "npm", "version": info["version"],
            "repositorio": info["repositorio"], "fecha_descarga": date.today().isoformat(),
            "tiene_codigo": True, "paquete": info["paquete"],
            "nombre_registro_mcp": info["nombre_registro"], "integridad": integ,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        ok += 1
        print(f"  [{ok}/{a.n}] {info['paquete']}@{info['version']}")
    print(f"\nListo: {ok} servidores en {salida}. Fallos: {len(fallos)}")
    for p, e in fallos[:10]:
        print(f"  - {p}: {e}")


if __name__ == "__main__":
    main()
