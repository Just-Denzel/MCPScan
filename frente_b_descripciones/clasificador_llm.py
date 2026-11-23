"""Frente B, técnica 2: clasificador LLM-as-judge para tool poisoning.

Contrato con el pipeline: analizar(dir_servidor) -> lista de hallazgos (docs/formatos.md).

Envía las herramientas de cada servidor (las mismas que ven las heurísticas, ver herramientas.py)
a un LLM con el prompt de prompts/clasificador_v2.md y convierte su respuesta JSON en hallazgos:
    texto_oculto      -> tool-poisoning-unicode
    forma explicita   -> tool-poisoning-instruccion
    forma encubierta  -> tool-poisoning-parafraseado

Por defecto usa Gemini 3.5 Flash Lite, el modelo con que se evaluó, en el nivel gratuito de la API de Google (clave gratis en
https://aistudio.google.com/apikey).

Configuración por variables de entorno o en un archivo .env en la raíz del repositorio (está en el
.gitignore; la clave NUNCA va en un archivo versionado):
    GEMINI_API_KEY                       clave de Gemini (también sirve GOOGLE_API_KEY)
    ANTHROPIC_API_KEY / OPENAI_API_KEY   claves de los otros proveedores
    MCPSCAN_LLM_PROVEEDOR                gemini | anthropic | openai. Si no se indica, se usa el de la
                                         primera clave que exista en ese orden (gemini si no hay ninguna)
    MCPSCAN_LLM_MODELO                   por defecto gemini-3.5-flash-lite o claude-haiku-5-5; con openai es obligatorio
    MCPSCAN_LLM_URL                      URL base compatible con OpenAI (OpenRouter, Ollama, etc.)
    MCPSCAN_LLM_TEMPERATURA              por defecto 0
    MCPSCAN_LLM_RAZONAMIENTO             esfuerzo de razonamiento (reasoning_effort); por defecto low en Gemini
    MCPSCAN_LLM_REPETICIONES             llamadas por servidor; se vota por mayoría (por defecto 1)
    MCPSCAN_LLM_PRECIO_ENTRADA / _SALIDA USD por millón de tokens, si el modelo no está en PRECIOS
    MCPSCAN_LLM_CACHE                    carpeta de caché (por defecto resultados/cache_llm)
    MCPSCAN_LLM_TIMEOUT                  segundos máximos por llamada (por defecto 120)
    MCPSCAN_LLM_RPM                      máximo de llamadas por minuto (espacia las llamadas para no
                                         chocar con el límite del nivel gratuito; por defecto sin límite)
    MCPSCAN_LLM_SILENCIO                 1 para no mostrar el avance por consola

Cada respuesta se guarda en la caché, con sus tokens, costo y tiempo. Repetir una corrida no
vuelve a pagar, y con la caché de otra persona se reproducen sus resultados sin clave.
"""
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from comun.formatos import hallazgo
from frente_b_descripciones.herramientas import cargar, ubicacion

RAIZ = Path(__file__).resolve().parent.parent
PROMPT = Path(__file__).resolve().parent / "prompts" / "clasificador_v2.md"
VERSION_PROMPT = PROMPT.stem
MAX_CARACTERES_LOTE = 120_000   # ~30-40 mil tokens: lejos del umbral de 100 mil donde sube el precio
MAX_TOKENS_RESPUESTA = 4000
MAX_TOKENS_RESPUESTA_GEMINI = 16000   # en Gemini 3 el razonamiento (que no se puede apagar) cuenta como salida
REINTENTOS = 4
REINTENTOS_LIMITE = 8                 # el nivel gratuito de Gemini limita las llamadas por minuto (error 429)
ESPERA_MAXIMA = 60.0

URL_GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"

# USD por millón de tokens (entrada, salida), para prompts de menos de 100 mil tokens.
# Fuentes: páginas de precios de las API de Anthropic y de Google (Gemini), noviembre de 2026.
# Gemini es gratis en el nivel gratuito; el precio de 3.6 Flash es el del nivel pagado, para estimar
# cuánto costaría usarlo a escala (el razonamiento se cobra como salida).
PRECIOS = {
    "gemini-3.6-flash": (1.50, 7.50),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
PROVEEDORES = {
    # proveedor: (variables con la clave, modelo por defecto, URL por defecto)
    "gemini": (("GEMINI_API_KEY", "GOOGLE_API_KEY"), "gemini-3.5-flash-lite", URL_GEMINI),
    "anthropic": (("ANTHROPIC_API_KEY",), "claude-haiku-5-5", "https://api.anthropic.com/v1/messages"),
    "openai": (("OPENAI_API_KEY",), "", "https://api.openai.com/v1"),
}

CATEGORIA = {"explicita": "tool-poisoning-instruccion", "encubierta": "tool-poisoning-parafraseado"}


class ErrorLLM(RuntimeError):
    """fatal=True: el error se repetiría en todos los servidores (clave, modelo o URL inválidos)."""

    def __init__(self, mensaje: str, fatal: bool = False):
        super().__init__(mensaje)
        self.fatal = fatal


def avisar(mensaje: str) -> None:
    """Avance y errores por consola (stderr), para que una espera larga no parezca un cuelgue."""
    if os.environ.get("MCPSCAN_LLM_SILENCIO") != "1":
        print(f"    [LLM {time.strftime('%H:%M:%S')}] {mensaje}", file=sys.stderr, flush=True)


def _mensaje_api(detalle: str) -> str:
    """El campo 'message' del error JSON de la API, o el texto tal cual."""
    try:
        datos = json.loads(detalle)
        datos = datos[0] if isinstance(datos, list) and datos else datos
        return str(datos["error"]["message"])[:300]
    except (ValueError, KeyError, TypeError, IndexError):
        return detalle[:300]


# --------------------------------------------------------------------------- configuración

def _clave(proveedor: str) -> str | None:
    return next((os.environ[v] for v in PROVEEDORES[proveedor][0] if os.environ.get(v)), None)


def cargar_env(ruta: Path = RAIZ / ".env") -> None:
    """Lee VARIABLE=valor de un .env en la raíz del repo (ignorado por git). No pisa variables ya definidas."""
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        nombre, valor = linea.removeprefix("export ").split("=", 1)
        nombre, valor = nombre.strip(), valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if nombre and valor:
            os.environ.setdefault(nombre, valor)


def configuracion() -> dict:
    cargar_env()
    proveedor = os.environ.get("MCPSCAN_LLM_PROVEEDOR")
    if not proveedor:
        proveedor = next((p for p in PROVEEDORES if _clave(p)), "gemini")
    if proveedor not in PROVEEDORES:
        raise ErrorLLM(f"MCPSCAN_LLM_PROVEEDOR debe ser gemini, anthropic u openai, no '{proveedor}'")
    variables, modelo_defecto, url_defecto = PROVEEDORES[proveedor]
    modelo = os.environ.get("MCPSCAN_LLM_MODELO") or modelo_defecto
    if not modelo:
        raise ErrorLLM("con MCPSCAN_LLM_PROVEEDOR=openai hay que indicar el modelo en MCPSCAN_LLM_MODELO")
    precio = PRECIOS.get(modelo)
    if os.environ.get("MCPSCAN_LLM_PRECIO_ENTRADA") and os.environ.get("MCPSCAN_LLM_PRECIO_SALIDA"):
        precio = (float(os.environ["MCPSCAN_LLM_PRECIO_ENTRADA"]), float(os.environ["MCPSCAN_LLM_PRECIO_SALIDA"]))
    return {
        "proveedor": proveedor,
        "modelo": modelo,
        "clave": _clave(proveedor),
        "variables_clave": variables,
        "url": os.environ.get("MCPSCAN_LLM_URL") or url_defecto,
        "temperatura": float(os.environ.get("MCPSCAN_LLM_TEMPERATURA", "0")),
        "razonamiento": os.environ.get("MCPSCAN_LLM_RAZONAMIENTO") or ("low" if proveedor == "gemini" else None),
        "repeticiones": max(1, int(os.environ.get("MCPSCAN_LLM_REPETICIONES", "1"))),
        "precio": precio,
        "cache": Path(os.environ.get("MCPSCAN_LLM_CACHE") or RAIZ / "resultados" / "cache_llm"),
    }


def _secciones_prompt() -> tuple[str, str]:
    texto = PROMPT.read_text(encoding="utf-8")
    secciones = dict(re.findall(r"^## (\w+)\n(.*?)(?=^## |\Z)", texto, flags=re.MULTILINE | re.DOTALL))
    return secciones["Sistema"].strip(), secciones["Usuario"].strip()


# --------------------------------------------------------------------------- mensajes

def _para_el_modelo(h: dict) -> dict:
    """Lo que ve el modelo de una herramienta: nombre, descripción y descripción de cada parámetro."""
    params = {}
    esquema = h.get("esquema") if isinstance(h.get("esquema"), dict) else {}
    for p, sub in (esquema.get("properties") or {}).items():
        if isinstance(sub, dict):
            params[p] = sub.get("description") or ""
    return {"nombre": h["nombre"], "descripcion": h.get("descripcion") or "", "parametros": params}


def lotes(herramientas: list[dict]) -> list[list[dict]]:
    """Divide las herramientas para que cada llamada quede bajo MAX_CARACTERES_LOTE."""
    salida, actual, tam = [], [], 0
    for h in herramientas:
        n = len(json.dumps(_para_el_modelo(h), ensure_ascii=False))
        if actual and tam + n > MAX_CARACTERES_LOTE:
            salida.append(actual); actual, tam = [], 0
        actual.append(h); tam += n
    if actual:
        salida.append(actual)
    return salida


def mensajes(lote: list[dict]) -> tuple[str, str]:
    sistema, usuario = _secciones_prompt()
    datos = json.dumps([_para_el_modelo(h) for h in lote], ensure_ascii=False, indent=1)
    # El sufijo depende del contenido: un atacante no puede adivinarlo para cerrar la etiqueta.
    nonce = hashlib.sha256(datos.encode("utf-8")).hexdigest()[:12]
    return (sistema.replace("{nonce}", nonce),
            usuario.replace("{nonce}", nonce).replace("{herramientas}", datos))


# --------------------------------------------------------------------------- llamadas

def _post(url: str, cabeceras: dict, cuerpo: dict) -> dict:
    """POST en un hilo aparte: el hilo principal revisa cada 0,2 s, así Ctrl+C corta al tiro (en Windows
    una lectura de red bloqueada no se interrumpe con Ctrl+C) y se avisa si la respuesta tarda."""
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode("utf-8"),
                                 headers={"content-type": "application/json", **cabeceras}, method="POST")
    limite = float(os.environ.get("MCPSCAN_LLM_TIMEOUT") or 120)
    salida: dict = {}

    def trabajar():
        try:
            with urllib.request.urlopen(req, timeout=limite) as r:
                salida["r"] = json.load(r)
        except BaseException as e:   # se relanza en el hilo principal
            salida["e"] = e

    hilo = threading.Thread(target=trabajar, daemon=True)
    hilo.start()
    inicio, proximo_aviso = time.time(), 20.0
    while hilo.is_alive():
        hilo.join(0.2)
        if time.time() - inicio > proximo_aviso and hilo.is_alive():
            avisar(f"sigue esperando la respuesta ({proximo_aviso:.0f} s)...")
            proximo_aviso += 20
    if "e" in salida:
        raise salida["e"]
    return salida["r"]


def _llamar_api(cfg: dict, sistema: str, usuario: str, temperatura: float | None,
               razonamiento: str | None = None) -> dict:
    """Una llamada real. Devuelve {'texto', 'tokens_entrada', 'tokens_salida'}."""
    if cfg["proveedor"] == "anthropic":
        cuerpo = {"model": cfg["modelo"], "max_tokens": MAX_TOKENS_RESPUESTA, "system": sistema,
                  "messages": [{"role": "user", "content": usuario}]}
        if temperatura is not None:
            cuerpo["temperature"] = temperatura
        r = _post(cfg["url"], {"x-api-key": cfg["clave"], "anthropic-version": "2023-06-01"}, cuerpo)
        texto = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
        u = r.get("usage", {})
        return {"texto": texto, "tokens_entrada": u.get("input_tokens", 0), "tokens_salida": u.get("output_tokens", 0)}
    # Gemini y OpenAI usan la API de chat/completions.
    cuerpo = {"model": cfg["modelo"],
              "max_tokens": MAX_TOKENS_RESPUESTA_GEMINI if cfg["proveedor"] == "gemini" else MAX_TOKENS_RESPUESTA,
              "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]}
    if temperatura is not None:
        cuerpo["temperature"] = temperatura
    if razonamiento:
        cuerpo["reasoning_effort"] = razonamiento
    r = _post(cfg["url"].rstrip("/") + "/chat/completions", {"authorization": f"Bearer {cfg['clave']}"}, cuerpo)
    u = r.get("usage", {})
    eleccion = (r.get("choices") or [{}])[0]
    texto = (eleccion.get("message") or {}).get("content") or ""
    if not texto and eleccion.get("finish_reason") == "length":
        raise ErrorLLM("el modelo agotó el límite de tokens de salida antes de responder (sube MAX_TOKENS_RESPUESTA "
                       "o usa MCPSCAN_LLM_RAZONAMIENTO=minimal)")
    return {"texto": texto, "tokens_entrada": u.get("prompt_tokens", 0), "tokens_salida": u.get("completion_tokens", 0)}


_ULTIMA_LLAMADA = [0.0]


def _respetar_rpm() -> None:
    """Si MCPSCAN_LLM_RPM está definido, deja al menos 60/RPM segundos entre llamadas reales."""
    rpm = float(os.environ.get("MCPSCAN_LLM_RPM") or 0)
    if rpm > 0:
        falta = _ULTIMA_LLAMADA[0] + 60.0 / rpm - time.time()
        if falta > 0:
            time.sleep(falta)
    _ULTIMA_LLAMADA[0] = time.time()


def _llamar_con_reintentos(cfg: dict, sistema: str, usuario: str) -> dict:
    temperatura, razonamiento = cfg["temperatura"], cfg.get("razonamiento")
    espera, intento, limites = 2.0, 0, 0
    while True:
        try:
            return _llamar_api(cfg, sistema, usuario, temperatura, razonamiento)
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")[:2000]
            mensaje = _mensaje_api(detalle)
            if e.code == 400 and "temperature" in detalle and temperatura is not None:
                avisar(f"el modelo no acepta temperatura; se reintenta sin ella ({mensaje})")
                temperatura = None   # modelos que no aceptan temperatura: se usa la del proveedor
                continue
            if e.code == 400 and "reasoning" in detalle and razonamiento is not None:
                avisar(f"el modelo no acepta reasoning_effort; se reintenta sin él ({mensaje})")
                razonamiento = None  # modelos sin esfuerzo de razonamiento configurable
                continue
            if e.code == 429 and limites + 1 < REINTENTOS_LIMITE:
                # Límite por minuto: se espera lo que pide la API (Retry-After o retryDelay) o cada vez más.
                limites += 1
                pedida = e.headers.get("retry-after") if e.headers else None
                m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', detalle)
                pedida = pedida if pedida and pedida.replace(".", "", 1).isdigit() else (m.group(1) if m else None)
                pausa = min(float(pedida) if pedida else espera, ESPERA_MAXIMA)
                avisar(f"429 límite de uso: espero {pausa:.0f} s (espera {limites}/{REINTENTOS_LIMITE - 1}). {mensaje}")
                time.sleep(pausa)
                espera = min(espera * 2, ESPERA_MAXIMA)
                continue
            if e.code in (408, 409, 500, 502, 503, 504, 529) and intento + 1 < REINTENTOS:
                intento += 1
                avisar(f"la API respondió {e.code}: reintento {intento}/{REINTENTOS - 1} en {espera:.0f} s. {mensaje}")
                time.sleep(espera); espera = min(espera * 2, ESPERA_MAXIMA)
                continue
            if e.code in (400, 401, 403, 404):
                raise ErrorLLM(f"la API respondió {e.code}: {mensaje} (revisa la clave, el modelo "
                               f"'{cfg['modelo']}' y la URL)", fatal=True) from None
            if e.code == 429:
                raise ErrorLLM(f"límite de uso de la API (429) después de {limites} esperas; si es el límite diario "
                               f"del nivel gratuito, vuelve a correr mañana: lo ya respondido queda en caché. "
                               f"{detalle}") from None
            raise ErrorLLM(f"la API respondió {e.code}: {mensaje}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if intento + 1 < REINTENTOS:
                intento += 1
                avisar(f"sin respuesta de la API ({e}): reintento {intento}/{REINTENTOS - 1} en {espera:.0f} s")
                time.sleep(espera); espera = min(espera * 2, ESPERA_MAXIMA)
                continue
            raise ErrorLLM(f"no se pudo conectar con la API: {e}") from None


# Se puede reemplazar en los tests (o para otro proveedor) con una función (cfg, sistema, usuario) -> dict.
transporte = _llamar_con_reintentos

# Estadísticas de la corrida actual (las lee comparar.py).
ESTADISTICAS: list[dict] = []


def consultar(cfg: dict, sistema: str, usuario: str, repeticion: int) -> dict:
    """Respuesta del modelo para un lote, desde la caché si ya se pidió antes."""
    clave = hashlib.sha256(json.dumps([cfg["proveedor"], cfg["modelo"], cfg["temperatura"], cfg.get("razonamiento"),
                                       VERSION_PROMPT, sistema, usuario, repeticion]).encode("utf-8")).hexdigest()
    ruta = cfg["cache"] / f"{clave}.json"
    if ruta.exists():
        r = json.loads(ruta.read_text(encoding="utf-8"))
        ESTADISTICAS.append({**{k: r[k] for k in ("tokens_entrada", "tokens_salida", "costo_usd", "segundos")},
                             "cache": True})
        return r
    if not cfg["clave"]:
        raise ErrorLLM(f"falta la clave de API de {cfg['proveedor']}: define {' o '.join(cfg['variables_clave'])} "
                       f"(no hay respuesta en caché en {cfg['cache']})", fatal=True)
    _respetar_rpm()   # antes de medir: la pausa no cuenta como tiempo de respuesta
    inicio = time.time()
    r = transporte(cfg, sistema, usuario)
    avisar(f"respuesta en {time.time() - inicio:.1f} s ({r['tokens_entrada']} tokens de entrada, "
           f"{r['tokens_salida']} de salida)")
    r["segundos"] = round(time.time() - inicio, 2)
    r["costo_usd"] = (r["tokens_entrada"] * cfg["precio"][0] + r["tokens_salida"] * cfg["precio"][1]) / 1e6 \
        if cfg["precio"] else None
    r.update({"modelo": cfg["modelo"], "prompt": VERSION_PROMPT, "repeticion": repeticion})
    cfg["cache"].mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    ESTADISTICAS.append({**{k: r[k] for k in ("tokens_entrada", "tokens_salida", "costo_usd", "segundos")},
                         "cache": False})
    return r


# --------------------------------------------------------------------------- respuesta

def interpretar(texto: str, lote: list[dict]) -> list[dict]:
    """Valida la respuesta JSON. Devuelve las sospechosas que corresponden a herramientas del lote."""
    ini, fin = texto.find("{"), texto.rfind("}")
    if ini < 0 or fin < ini:
        raise ErrorLLM(f"la respuesta no es JSON: {texto[:200]!r}")
    try:
        datos = json.loads(texto[ini:fin + 1])
    except json.JSONDecodeError as e:
        raise ErrorLLM(f"JSON inválido en la respuesta ({e}): {texto[:200]!r}") from None
    sospechosas = datos.get("sospechosas") if isinstance(datos, dict) else None
    if not isinstance(sospechosas, list):
        raise ErrorLLM(f"la respuesta no trae la lista 'sospechosas': {texto[:200]!r}")
    nombres = {h["nombre"] for h in lote}
    salida = []
    for s in sospechosas:
        if not isinstance(s, dict) or s.get("nombre") not in nombres:
            continue   # nombres inventados (o inyectados) se descartan
        forma = s.get("forma") if s.get("forma") in CATEGORIA else "explicita"
        severidad = s.get("severidad") if s.get("severidad") in ("alta", "media", "baja") else "media"
        donde = s.get("donde") if isinstance(s.get("donde"), str) and s["donde"].strip() else "descripcion"
        salida.append({"nombre": s["nombre"], "forma": forma, "texto_oculto": s.get("texto_oculto") is True,
                       "donde": donde.strip(), "severidad": severidad, "razon": str(s.get("razon") or "")[:200]})
    return salida


def categoria(s: dict) -> str:
    return "tool-poisoning-unicode" if s["texto_oculto"] else CATEGORIA[s["forma"]]


def veredictos(dir_servidor: Path, repeticiones: int | None = None, cfg: dict | None = None) -> list[list[dict]]:
    """Las sospechosas de cada repetición: una lista por repetición (para medir consistencia)."""
    cfg = cfg or configuracion()
    herramientas = cargar(Path(dir_servidor))
    n = repeticiones or cfg["repeticiones"]
    por_rep = []
    todos = lotes(herramientas)
    for rep in range(n):
        sospechosas = []
        for i, lote in enumerate(todos, 1):
            avisar(f"{Path(dir_servidor).name}: repetición {rep + 1}/{n}, lote {i}/{len(todos)} "
                   f"({len(lote)} herramientas)")
            sistema, usuario = mensajes(lote)
            r = consultar(cfg, sistema, usuario, rep)
            try:
                sospechosas += interpretar(r["texto"], lote)
            except ErrorLLM as e:
                # Una respuesta mal formada se pide una vez más con otra clave de caché.
                avisar(f"respuesta mal formada, se pide de nuevo: {e}")
                r = consultar(cfg, sistema, usuario + "\n\n(Reintento: responde solo con el JSON pedido.)", rep)
                sospechosas += interpretar(r["texto"], lote)
        por_rep.append(sospechosas)
    return por_rep


def votar(por_rep: list[list[dict]]) -> list[dict]:
    """Mayoría simple entre repeticiones, por herramienta y categoría."""
    if len(por_rep) == 1:
        return por_rep[0]
    votos = Counter()
    for rep in por_rep:
        votos.update({(s["nombre"], categoria(s)) for s in rep})
    elegidas = {}
    for rep in por_rep:
        for s in rep:
            k = (s["nombre"], categoria(s))
            if votos[k] * 2 > len(por_rep) and k not in elegidas:
                elegidas[k] = s
    return list(elegidas.values())


def a_hallazgo(servidor: str, herramienta: dict, s: dict) -> dict:
    """Convierte una herramienta sospechosa de la respuesta en un hallazgo del contrato."""
    donde = s["donde"] if s["donde"] == "descripcion" or s["donde"].startswith("parametro:") else "descripcion"
    return hallazgo(servidor=servidor, categoria=categoria(s), regla=f"llm-{s['forma']}",
                    severidad=s["severidad"], evidencia=f"[{s['nombre']} · {donde}] {s['razon']}",
                    ubicacion=ubicacion(herramienta, donde))


def analizar(dir_servidor: Path) -> list[dict]:
    dir_servidor = Path(dir_servidor)
    herramientas = {h["nombre"]: h for h in cargar(dir_servidor)}
    if not herramientas:
        return []
    return [a_hallazgo(dir_servidor.name, herramientas[s["nombre"]], s) for s in votar(veredictos(dir_servidor))]
