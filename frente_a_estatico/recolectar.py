#!/usr/bin/env python3
"""Descarga N servidores MCP públicos de npm al formato de corpus, SIN ejecutar nada.

Requiere Python 3.12 o superior. Tres formas de uso, desde la raíz del repositorio:

  1. Muestra nueva, sorteada del registry de hoy (cambia según la fecha):
         python frente_a_estatico/recolectar.py corpus/real --n 100 [--semilla 1]
  2. Guardar la lista exacta de una muestra ya descargada (sin descargar nada):
         python frente_a_estatico/recolectar.py corpus/real --exportar-muestra corpus/muestra_real.json
  3. Descargar exactamente esa misma muestra en otro computador:
         python frente_a_estatico/recolectar.py corpus/real --desde-muestra corpus/muestra_real.json

El registry de MCP cambia con el tiempo: la misma semilla en otra fecha da otra muestra.
Para que la muestra sea reproducible, se usa la forma 3.

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


def carpeta_de(salida: Path, paquete: str) -> Path:
    return salida / re.sub(r"[^a-zA-Z0-9._-]", "__", paquete.lstrip("@"))


def bajar_uno(salida: Path, info: dict, fecha: str | None = None) -> str:
    """Descarga y extrae un paquete. Devuelve 'nuevo' o 'ya estaba'; lanza excepción si falla.

    Si info trae "integridad" (muestra guardada), exige que el paquete de npm sea idéntico.
    """
    carpeta = carpeta_de(salida, info["paquete"])
    manifest = carpeta / "manifest.json"
    if manifest.exists():  # ya descargado antes
        previo = json.loads(manifest.read_text(encoding="utf-8"))
        if previo.get("version") == info["version"]:
            return "ya estaba"
    if carpeta.exists():  # a medias o de otra versión: se rehace
        shutil.rmtree(carpeta)
    try:
        datos, integ = descargar(info)
        if info.get("integridad") and integ != info["integridad"]:
            raise ValueError("el paquete en npm no coincide con la integridad guardada en la muestra")
        extraer(datos, carpeta / "codigo")
    except Exception:
        if carpeta.exists():
            shutil.rmtree(carpeta)
        raise
    manifest.write_text(json.dumps({
        "nombre": carpeta.name, "fuente": "npm", "version": info["version"],
        "repositorio": info.get("repositorio"), "fecha_descarga": fecha or date.today().isoformat(),
        "tiene_codigo": True, "paquete": info["paquete"],
        "nombre_registro_mcp": info.get("nombre_registro"), "integridad": integ,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return "nuevo"


def exportar_muestra(salida: Path, archivo: Path) -> None:
    """Guarda la lista exacta (paquete, versión, integridad) del corpus ya descargado."""
    filas = []
    for m in sorted(salida.glob("*/manifest.json")):
        d = json.loads(m.read_text(encoding="utf-8"))
        if d.get("fuente") != "npm":
            continue
        filas.append({"paquete": d["paquete"], "version": d["version"], "integridad": d["integridad"],
                      "repositorio": d.get("repositorio"), "nombre_registro": d.get("nombre_registro_mcp")})
    if not filas:
        raise SystemExit(f"No hay servidores descargados en {salida}.")
    fechas = sorted({json.loads(m.read_text(encoding="utf-8")).get("fecha_descarga", "")
                     for m in salida.glob("*/manifest.json")})
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps({
        "descripcion": "Muestra de servidores MCP de npm analizada en MCPScan. "
                       "Se reproduce con: python frente_a_estatico/recolectar.py corpus/real --desde-muestra " + archivo.as_posix(),
        "fecha_descarga": fechas[0] if len(fechas) == 1 else fechas,
        "fuente": "registry oficial de MCP + npm",
        "servidores": filas,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"Muestra de {len(filas)} servidores guardada en {archivo}. Versiónala en git para reproducir el análisis.")


def desde_muestra(salida: Path, archivo: Path) -> None:
    """Descarga exactamente los paquetes y versiones de una muestra guardada."""
    muestra = json.loads(archivo.read_text(encoding="utf-8"))
    fecha = muestra.get("fecha_descarga") if isinstance(muestra.get("fecha_descarga"), str) else None
    servidores = muestra["servidores"]
    nuevos = ya = 0
    fallos = []
    for i, info in enumerate(servidores, 1):
        try:
            estado = bajar_uno(salida, info, fecha)
        except Exception as e:
            fallos.append((info["paquete"], str(e)))
            continue
        nuevos += estado == "nuevo"
        ya += estado == "ya estaba"
        print(f"  [{i}/{len(servidores)}] {info['paquete']}@{info['version']} ({estado})")
    extra = {d.name for d in salida.glob("*/") if (d / "manifest.json").exists()} - {
        carpeta_de(salida, s["paquete"]).name for s in servidores}
    print(f"\nListo: {nuevos} descargados, {ya} ya estaban. Fallos: {len(fallos)}")
    for p, e in fallos:
        print(f"  - {p}: {e}")
    if extra:
        print(f"ATENCIÓN: {salida} tiene {len(extra)} servidores que no están en la muestra; "
              "bórralos o los resultados no serán comparables.")
    if fallos:
        raise SystemExit(1)


def muestra_nueva(salida: Path, n: int, semilla: int) -> None:
    print("Listando servidores del registry oficial...")
    cand = candidatos()
    print(f"{len(cand)} paquetes npm candidatos")
    claves = sorted(cand)
    random.Random(semilla).shuffle(claves)
    ok, fallos = 0, []
    for k in claves:
        if ok >= n:
            break
        try:
            bajar_uno(salida, cand[k])
        except Exception as e:
            fallos.append((cand[k]["paquete"], str(e)))
            continue
        ok += 1
        print(f"  [{ok}/{n}] {cand[k]['paquete']}@{cand[k]['version']}")
    print(f"\nListo: {ok} servidores en {salida}. Fallos: {len(fallos)}")
    for p, e in fallos[:10]:
        print(f"  - {p}: {e}")
    print("Para reproducir esta misma muestra, guárdala con --exportar-muestra.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Descarga servidores MCP de npm sin ejecutarlos.")
    ap.add_argument("salida", help="carpeta del corpus, por ejemplo corpus/real")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--semilla", type=int, default=1)
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--exportar-muestra", metavar="ARCHIVO",
                      help="guarda la lista exacta del corpus ya descargado (no descarga nada)")
    modo.add_argument("--desde-muestra", metavar="ARCHIVO",
                      help="descarga exactamente los paquetes y versiones de esa lista")
    a = ap.parse_args()
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    if a.exportar_muestra:
        exportar_muestra(salida, Path(a.exportar_muestra))
    elif a.desde_muestra:
        desde_muestra(salida, Path(a.desde_muestra))
    else:
        muestra_nueva(salida, a.n, a.semilla)


if __name__ == "__main__":
    main()
