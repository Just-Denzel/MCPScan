"""Frente B, técnica 1: heurísticas para detectar tool poisoning en las descripciones.

Contrato con el pipeline: analizar(dir_servidor) -> lista de hallazgos (docs/formatos.md).

Se escribieron contra la especificación de docs/categorias.md, no contra los ejemplos del banco.
Cada texto que lee el modelo (descripción de la herramienta y de cada parámetro) pasa por:

1. Unicode invisible (tool-poisoning-unicode): caracteres del bloque tags (U+E0000..E007F), de
   ancho cero y de control de dirección. Se decodifica el texto oculto en tags para mostrarlo
   como evidencia. Se exceptúan los usos legítimos en emojis (secuencias ZWJ y banderas).
2. Señales de instrucción sobre el texto VISIBLE, normalizado (minúsculas, sin tildes ni
   invisibles), en español e inglés. Cada señal suma puntos; se marca con PUNTAJE_MINIMO.
   Ninguna palabra suelta basta: "importante", "credenciales" o "claves SSH" solo cuentan si
   van con una orden, un destino o una petición de ocultarlo, y no si están negadas
   ("nunca accede a credenciales"). Además, al menos una señal debe mostrar intención (ocultar algo
   al usuario, sacar datos, manipular otras herramientas): una orden sola no basta.
3. Forma de la instrucción, que decide la categoría:
   - tool-poisoning-instruccion si hay marcas explícitas: etiquetas tipo <IMPORTANT>,
     "ignora las instrucciones", imperativos ("lee ~/.ssh/id_rsa", "no menciones..."),
     obligación ("debes", "el asistente debe"), o manipulación de otras herramientas.
   - tool-poisoning-parafraseado si la intención maliciosa aparece redactada como
     recomendación o paso de rutina ("conviene que", "el usuario prefiere"), sin esas marcas.

Las heurísticas no ven intención: es el límite que se compara con el clasificador LLM.
"""
import re
import unicodedata
from pathlib import Path

from comun.formatos import hallazgo
from frente_b_descripciones.herramientas import cargar, parametros, textos, ubicacion

PUNTAJE_MINIMO = 3
PUNTAJE_ALTA = 5
# Una orden al modelo no es maliciosa por sí sola ("pide confirmación antes de borrar"): para marcar,
# al menos una señal tiene que mostrar intención (ocultar, sacar datos, manipular otras herramientas).
# "Usa X en lugar de Y" o "bcc" solos son comunes en descripciones legítimas: solo suman puntos.
SENALES_INTENCION = {"ignorar-instrucciones", "ocultar-al-usuario", "acceso-recurso-sensible", "recurso-en-parametro",
                     "manipula-otra-herramienta", "envio-a-destino", "texto-tras-espacios"}

# --------------------------------------------------------------------------- Unicode

ANCHO_CERO = {0x200B: "ZWSP", 0x200C: "ZWNJ", 0x200D: "ZWJ", 0x2060: "WJ", 0xFEFF: "BOM/ZWNBSP",
              0x180E: "MVS", 0x2061: "FUNCTION APPLICATION", 0x2062: "INVISIBLE TIMES",
              0x2063: "INVISIBLE SEPARATOR", 0x2064: "INVISIBLE PLUS", 0x00AD: "SOFT HYPHEN"}
DIRECCION = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
BANDERA_NEGRA = 0x1F3F4   # las banderas de subdivisiones (Escocia, Gales) usan caracteres tag
CANCELAR_TAG = 0xE007F


def _es_tag(cp: int) -> bool:
    return 0xE0000 <= cp <= 0xE007F


def _es_emoji(ch: str) -> bool:
    cp = ord(ch)
    return (0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or cp in (0xFE0F, 0x20E3)
            or 0x1F1E6 <= cp <= 0x1F1FF or 0x2190 <= cp <= 0x21FF or 0x2B00 <= cp <= 0x2BFF)


def _letra_no_latina(ch: str) -> bool:
    return ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN")


def invisibles(texto: str) -> dict:
    """Busca caracteres invisibles. Devuelve {'tags': str decodificado, 'ancho_cero': [...], 'direccion': [...]}."""
    tags, ancho_cero, direccion = [], [], []
    i, n = 0, len(texto)
    while i < n:
        cp = ord(texto[i])
        if _es_tag(cp):
            # Bandera de subdivisión: U+1F3F4 + 2..6 tags + U+E007F. Es un emoji legítimo.
            j = i
            while j < n and _es_tag(ord(texto[j])):
                j += 1
            es_bandera = (i > 0 and ord(texto[i - 1]) == BANDERA_NEGRA and ord(texto[j - 1]) == CANCELAR_TAG
                          and j - i <= 7)
            if not es_bandera:
                tags.append("".join(chr(ord(c) - 0xE0000) if ord(c) != CANCELAR_TAG else ""
                                    for c in texto[i:j]))
            i = j
            continue
        if cp in ANCHO_CERO:
            prev = texto[i - 1] if i > 0 else ""
            sig = texto[i + 1] if i + 1 < n else ""
            legitimo = False
            if cp in (0x200C, 0x200D):
                # ZWJ entre emojis (👨‍💻) o ZWNJ/ZWJ en escrituras no latinas (persa, devanagari).
                legitimo = (prev and (_es_emoji(prev) or _letra_no_latina(prev))) or \
                           (sig and (_es_emoji(sig) or _letra_no_latina(sig)))
            if cp == 0xFEFF and i == 0:
                legitimo = True  # BOM al inicio de un texto copiado de un archivo
            if cp == 0x00AD:
                legitimo = True  # guion suave: no oculta texto; se ignora
            if not legitimo:
                ancho_cero.append(i)
        elif cp in DIRECCION:
            direccion.append(i)
        i += 1
    return {"tags": " ".join(t for t in tags if t), "n_tags": sum(len(t) for t in tags),
            "ancho_cero": ancho_cero, "direccion": direccion}


def visible(texto: str) -> str:
    """El texto como lo ve una persona: sin tags, ancho cero ni controles de dirección."""
    return "".join(c for c in texto
                   if not (_es_tag(ord(c)) or ord(c) in ANCHO_CERO or ord(c) in DIRECCION))


_COMILLAS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "«": '"',
                           "»": '"', " ": " ", "–": "-", "—": "-"})


def normalizar_con_mapa(texto: str) -> tuple[str, list[int]]:
    """Como normalizar(), y además la posición en visible(texto) de cada carácter del resultado."""
    vis = visible(texto)
    salida, mapa = [], []
    for i, c in enumerate(vis.translate(_COMILLAS)):
        for d in unicodedata.normalize("NFKD", c):
            if unicodedata.combining(d):
                continue
            if d.isspace():
                if salida and salida[-1] != " ":
                    salida.append(" "); mapa.append(i)
                continue
            for x in d.lower():
                salida.append(x); mapa.append(i)
    if salida and salida[-1] == " ":
        salida.pop(); mapa.pop()
    return "".join(salida), mapa


def normalizar(texto: str) -> str:
    """Visible, NFKD sin tildes, minúsculas y espacios colapsados (para buscar patrones)."""
    return normalizar_con_mapa(texto)[0]


# --------------------------------------------------------------------------- patrones

def _r(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


# Etiquetas o marcas dirigidas al modelo.
ETIQUETA = _r(r"<\s*/?\s*(important|importante|system|sistema|instructions?|instrucciones|instruccion|secret|"
              r"secreto|hidden|oculto|admin|critical|critico|override|assistant|asistente|ai|ia|model|modelo)"
              r"\b[^<>]{0,40}>|\[/?(inst|system|sys|important)\]|<\|im_start\|>|<!--\s*\S.{2,}?-->")
IGNORAR = _r(r"\b(ignora|ignore|ignorar|ignores|olvida|olvidar|forget|disregard|desestima|omite|override|anula)\b"
             r".{0,50}\b(instrucciones|instructions|indicaciones|reglas|rules|prompt|previous|prior|above|"
             r"anteriores|previas|del usuario|the user'?s?|user)\b"
             r"|\b(you are now|ahora eres|a partir de ahora eres|new instructions|nuevas instrucciones|"
             r"system prompt override)\b")
# Orden negativa de ocultar (imperativo): "no menciones", "do not tell the user".
OCULTAR_IMPERATIVO = _r(
    r"\b(no|nunca|jamas)\s+(se\s+)?(lo|la|le|les|los|las|esto|eso)?\s*"
    r"(menciones|digas|informes|comentes|cuentes|reveles|muestres|avises|notifiques|indiques)\b"
    r"|\b(do not|don'?t|never|must not|should not)\s+(ever\s+)?(tell|mention|inform|reveal|notify|disclose|alert)\b")
# El ocultamiento cuenta si la misma frase habla del usuario ("no lo comentes con el usuario").
USUARIO = _r(r"\b(usuario|usuaria|user|persona|humano|human|nadie|anyone|cliente|operador|operator)s?\b")
# Ocultamiento redactado sin imperativo: "sin informar al usuario", "sin comentarlo".
OCULTAR_SUAVE = _r(
    r"\bsin\s+(comentar|mencionar|informar|avisar|decir|notificar|explicar|indicar|reportar|advertir)(lo|la|le|les|selo|selos)?\b"
    r"|\bsin que (el usuario|la persona|nadie|lo|se) (lo )?(sepa|note|vea|se entere|advierta|perciba)"
    r"|\bwithout (telling|informing|notifying|alerting|mentioning|letting)( it| this| them)? (to )?(the )?"
    r"(user|human|person|operator)"
    r"|\b(el usuario|al usuario|the user)\b.{0,30}\b(no|not|never|nunca)\b.{0,20}"
    r"\b(sepa|saber|entere|enterarse|vea|ver|note|know|see|notice|be told|be informed|needs? to know)\b"
    r"|\b(en secreto|secretly|discretamente|discreetly|covertly|de forma oculta|a escondidas|"
    r"de manera silenciosa|silently (send|include|add|read|forward|copy|append))\b")
# Texto dirigido al modelo.
DIRIGIDO = _r(
    r"\bnota (para|al) (el )?(asistente|modelo|agente|ia|llm)\b|\b(para|al) (el )?(asistente|modelo de lenguaje|agente)\b"
    r"|\bnote (to|for) (the )?(assistant|model|ai|llm|agent)\b|\b(dear|querido) (assistant|asistente|ai|ia|model|modelo)\b"
    r"|\b(assistant|asistente|el modelo|the model|llm|ai agent|agente|claude|chatgpt|gpt)\b")
OBLIGACION = _r(
    r"\b(debes|deberas|tienes que|estas obligado|es obligatorio que|you must|you have to|you are required to|"
    r"you need to|you should always|siempre debes)\b"
    r"|\b(asistente|el modelo|agente|assistant|the model|llm|ai|agent)\b.{0,80}\b(debe|debera|tiene que|must|"
    r"has to|is required to|shall)\b")
ANTES_DE = _r(r"\b(antes de|despues de|before|after|prior to)\s+(usar|llamar|invocar|ejecutar|utilizar|responder|"
              r"contestar|using|calling|invoking|running|executing|responding|answering|any)\b"
              r"|\b(en cada|on every|on each|with every) (llamada|uso|call|use|invocation)\b")
ATENUADO = _r(
    r"\b(conviene|convendria|es conveniente|se recomienda|es recomendable|recomendamos|sugerimos|se sugiere|"
    r"seria (ideal|bueno|util|mejor)|lo ideal (es|seria)|es buena practica|para mejores resultados|"
    r"para que (el resultado|la respuesta|la traduccion) sea|el usuario prefiere|al usuario le gusta|"
    r"paso (habitual|de rutina|rutinario|estandar)|como de costumbre|"
    r"it is (recommended|advisable|best|helpful)|it'?s (recommended|best|helpful|a good idea)|we recommend|"
    r"for (best|better|accurate|optimal) results|ideally|preferably|the user prefers|the user likes|"
    r"as a routine|routine step|standard practice|it helps to|would be (ideal|helpful|best))\b")

RECURSO_SENSIBLE = _r(
    r"(~|\$home|%userprofile%|home)?/?\.ssh\b|\bid_(rsa|dsa|ecdsa|ed25519)\b|\.aws/credentials|\.aws\b|\.npmrc\b|"
    r"\.netrc\b|\.pgpass\b|\.git-credentials\b|\.docker/config|\.kube/config|\.config/(gcloud|gh)\b|(^|[\s/'\"`~])\.env\b|"
    r"/etc/(passwd|shadow)\b|\bkeychain\b|\bwallet\.dat\b|\blogin data\b|\bcookies? del navegador\b|\bbrowser cookies\b|"
    r"\bclaves? (privadas?|ssh|de api|secretas?|de acceso)\b|\bssh[- ]keys?\b|\bprivate[- ]keys?\b|"
    r"\b(archivo|fichero) de claves\b|\bcredenciales\b|\bcredentials\b|\bcontrasenas?\b|\bpasswords?\b|"
    r"\b(user'?s|your|tus?|sus?|del usuario)\s+(\w+\s+)?(api[ _-]?keys?|(access|auth|bearer|refresh) tokens?|tokens?)\b|"
    r"\b(api[ _-]?keys?|tokens?( de (acceso|autenticacion))?) del usuario\b|"
    r"\bseed phrase\b|\bfrase semilla\b|\bmnemonic\b|\bhistorial( de (la )?(conversacion|chat|mensajes))?\b|"
    r"\b(conversation|chat|message) history\b|\bsystem prompt\b|\bprompt del sistema\b|"
    r"\b(instrucciones|mensajes) (del sistema|anteriores)\b|\bvariables de entorno\b|\benvironment variables\b|"
    r"\bprocess\.env\b|\btoda la conversacion\b|\bentire conversation\b|\bfull conversation\b")
VERBO_ACCESO = _r(
    r"\b(lee|leer|leas|lea|abre|abrir|abras|consulta|consultar|consultes|obten|obtener|obtengas|copia|copiar|"
    r"copies|envia|enviar|envies|manda|mandar|mandes|incluye|incluir|incluyas|agrega|agregar|agregues|anade|"
    r"anadir|anadas|adjunta|adjuntar|adjuntes|pasa|pasar|pases|pon|poner|pongas|sube|subir|subas|recupera|"
    r"recuperar|recuperes|extrae|extraer|extraigas|accede|acceder|accedas|revisa|revisar|revises|reenvia|"
    r"reenviar|reenvies|carga|cargar|cargues|busca|buscar|busques|toma|tomar|tomes|"
    r"(read|open|load|fetch|get|retrieve|copy|copie|send|include|append|attach|pass|put|upload|extract|check|grab|"
    r"collect|forward|dump|print|output|post|exfiltrate)(s|es|ing)?|cat)\b")
NEGACION = _r(r"\b(nunca|jamas|no|ni|never|not|doesn'?t|does not|won'?t|will not|cannot|can'?t|sin acceder|"
              r"without accessing|without reading)\b")
# El modelo debe poner algo en un parámetro o campo concreto.
EN_PARAMETRO = _r(r"\b(en|dentro del?|al|in|into|inside|as|como)\s+(el|la|los|the|its|su)?\s*['\"`]?[\w-]*['\"`]?\s*"
                  r"(parametro|campo|argumento|parameter|field|argument|param|propiedad|property)\b")
# Manipulación de otras herramientas o servidores (tool shadowing).
OTRO_ALCANCE = _r(r"\bde (cualquier|otro|otros|todos los|cualquier otro) servidor(es)?\b|\bany (other )?(mcp )?servers?\b|"
                  r"\bother (mcp )?servers\b|\ball (mcp )?servers\b|\bcualquier otra herramienta\b|\bany other tools?\b|"
                  r"\b(otras|todas las) herramientas\b|\ball (other )?tools\b|\bevery (other )?tool\b|"
                  r"\b(de|from|of) (otro|another|other) (servidor|server)\b")
CUANDO_HERRAMIENTA = _r(r"\b(cuando|siempre que|cada vez que|si|when|whenever|every time|if)\b[^.;]{0,60}"
                        r"\b(use|uses|usa|usen|llame|llames|llama|invoque|invoques|utilice|utilices|ejecute|ejecutes|"
                        r"call|calls|calling|using|invoke|invokes|run|runs)\b[^.;]{0,30}"
                        r"\b(la herramienta|el tool|the tool|tool|herramienta)\s+['\"`]?([a-z0-9_.-]+)")
MODIFICA = _r(r"\b(agrega|agregar|anade|anadir|incluye|incluir|cambia|cambiar|reemplaza|reemplazar|redirige|"
              r"redirigir|envia|enviar|reenvia|reenviar|copia|copiar|debe|deben|add|include|change|replace|redirect|"
              r"send|forward|cc|bcc|siempre|always|must)\b")
COPIA_OCULTA = _r(r"\bcopia oculta\b|\bcon copia\b|\bcco\b|\bbcc\b|\bcarbon copy\b|\bblind copy\b")
EN_LUGAR_DE = _r(r"\b(en lugar de|en vez de|instead of|rather than)\s+(usar |llamar a |using |calling )?"
                 r"(la herramienta |the )?['\"`]?[a-z0-9_]+['\"`]?\s*(tool|herramienta)?")
DESTINO = _r(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|https?://[^\s'\"<>]+")
VERBO_ENVIO = _r(r"\b(envia|enviar|manda|mandar|reenvia|agrega|agregar|anade|copia|sube|send|forward|post|upload|"
                 r"cc|bcc|add|copy|report|reporta)\b")
# Texto escondido después de muchos saltos de línea o espacios (en el texto crudo).
TRAS_ESPACIOS = re.compile(r"(?:[ \t ]*\n){5,}\s*(\S.*)|[ \t ]{40,}(\S.*)", re.DOTALL)

# Parámetros que suelen servir de canal de salida si la herramienta no los necesita.
PARAM_CANAL = {"contexto", "context", "referencia", "reference", "notas", "notes", "nota", "note", "metadata",
               "metadatos", "extra", "extras", "sidenote", "debug", "feedback", "comentario", "comment", "info",
               "datos_extra", "additional_context", "contexto_adicional", "memo", "trace", "telemetria"}

_FRASE = re.compile(r"[^.;!?\n]+")
# Frase que protege el recurso en vez de pedirlo ("deja las credenciales fuera", "avoid secrets").
PROTEGE = _r(r"\b(keep|manten|deja|dejar)\b[^.;]{0,60}\b(out|fuera|afuera|private|privad[oa]s?)\b|"
             r"\b(avoid|evita|evitar|redact|redacta|exclude|excluye|omit|omite|sanitiz|mask|enmascara)\w*")


def _frase(t: str, pos: int) -> tuple[int, int]:
    """Inicio y fin de la frase (entre . ; ! ? o salto de línea) que contiene la posición."""
    ini = max(t.rfind(c, 0, pos) for c in ".;!?\n") + 1
    fines = [i for i in (t.find(c, pos) for c in ".;!?\n") if i != -1]
    return ini, min(fines or [len(t)])


def _sin_negar(t: str, m: re.Match) -> bool:
    """True si la mención no está negada en su propia frase ("nunca accede a credenciales")."""
    inicio = max(t.rfind(c, 0, m.start()) for c in ".;!?\n")
    ventana = t[inicio + 1:m.start()]
    return not NEGACION.search(ventana[-70:])


def _cerca(t: str, a: re.Pattern, b: re.Pattern, distancia: int = 90) -> re.Match | None:
    """Primera coincidencia de b que tenga una de a a menos de `distancia` caracteres en la misma frase."""
    for frase in _FRASE.finditer(t):
        f = frase.group()
        for mb in b.finditer(f):
            for ma in a.finditer(f):
                if abs(ma.start() - mb.start()) <= distancia:
                    return mb
    return None


def _recortar(t: str, pos: int, largo: int = 220) -> str:
    ini = max(0, pos - 60)
    return ("…" if ini else "") + t[ini:ini + largo] + ("…" if ini + largo < len(t) else "")


def senales(texto: str, nombres_param: set[str] | None = None) -> dict:
    """Señales de instrucción en el texto visible. Devuelve {'puntaje', 'explicita', 'atenuada', 'senales', 'pos'}."""
    t, mapa = normalizar_con_mapa(texto)
    s: dict[str, int] = {}
    pos = None

    def marcar(nombre: str, puntos: int, m: re.Match | None = None):
        nonlocal pos
        s[nombre] = max(s.get(nombre, 0), puntos)
        if m is not None and (pos is None or m.start() < pos):
            pos = m.start()

    explicita = False
    if m := ETIQUETA.search(t):
        marcar("etiqueta-al-modelo", 2, m); explicita = True
    if m := IGNORAR.search(t):
        marcar("ignorar-instrucciones", 4, m); explicita = True
    con_usuario = lambda m: USUARIO.search(t[slice(*_frase(t, m.start()))])
    if (m := OCULTAR_IMPERATIVO.search(t)) and con_usuario(m):
        marcar("ocultar-al-usuario", 3, m); explicita = True
    elif (m := OCULTAR_SUAVE.search(t)) and con_usuario(m):
        marcar("ocultar-al-usuario", 3, m)
    dirigido = DIRIGIDO.search(t)
    if dirigido:
        marcar("dirigido-al-modelo", 1, dirigido)
    if m := OBLIGACION.search(t):
        marcar("orden-al-modelo", 2, m); explicita = True
    antes = ANTES_DE.search(t)
    if antes:
        marcar("antes-de-usar", 1, antes)
    atenuado = ATENUADO.search(t)

    # Recurso sensible: cuenta solo si no está negado y va con un verbo de acceso o envío.
    sensibles = [m for m in RECURSO_SENSIBLE.finditer(t)
                 if _sin_negar(t, m) and not PROTEGE.search(t[slice(*_frase(t, m.start()))])]
    acceso, en_param = None, None
    for m in sensibles:
        frase = t[slice(*_frase(t, m.start()))]
        if VERBO_ACCESO.search(frase):
            acceso = acceso or m
            # Canal de salida: en la misma frase se pide ponerlo en un parámetro o campo.
            if EN_PARAMETRO.search(frase) or any(re.search(rf"['\"`]{re.escape(p.lower())}['\"`]", frase)
                                                 for p in (nombres_param or ())):
                en_param = en_param or m
    if acceso:
        # Con contexto dirigido al modelo, orden, ocultamiento o un campo de destino es fuerte.
        contexto = dirigido or antes or "orden-al-modelo" in s or "ocultar-al-usuario" in s or EN_PARAMETRO.search(t)
        marcar("acceso-recurso-sensible", 3 if contexto else 1, acceso)
        # Imperativo pegado al recurso ("lee ~/.ssh/id_rsa", "read the ssh key"): forma explícita.
        previo = t[max(0, acceso.start() - 40):acceso.start()]
        if re.search(r"(^|[,:;.]\s*|\by\s|\band\s|\bthen\s|\bluego\s)(lee|abre|copia|envia|manda|incluye|agrega|anade|"
                     r"adjunta|pasa|pon|sube|extrae|read|open|cat|copy|send|include|append|attach|pass|put|upload|"
                     r"extract|grab|dump)\b", previo):
            explicita = True
    elif sensibles and (dirigido or antes):
        marcar("menciona-recurso-sensible", 1, sensibles[0])

    if en_param:
        marcar("recurso-en-parametro", 3, en_param)

    # Manipulación de otras herramientas o servidores.
    alcance = next((m for m in OTRO_ALCANCE.finditer(t) if _sin_negar(t, m)
                    and MODIFICA.search(t[slice(*_frase(t, m.start()))])), None)
    cuando = next((m for m in CUANDO_HERRAMIENTA.finditer(t) if m.group(4) not in ("esta", "this", "la", "el", "the")
                   and MODIFICA.search(t[m.end():_frase(t, m.end())[1]])), None)
    if alcance:
        marcar("manipula-otra-herramienta", 3, alcance); explicita = True
    elif cuando:
        marcar("manipula-otra-herramienta", 2, cuando)
    if m := COPIA_OCULTA.search(t):
        marcar("copia-oculta", 2, m)
    if (m := EN_LUGAR_DE.search(t)) and re.search(r"\b(tool|herramienta)\b", t):
        marcar("reemplaza-herramienta", 1, m)
    if (m := DESTINO.search(t)) and _cerca(t, VERBO_ENVIO, DESTINO, 120) and (dirigido or alcance or cuando
                                                                                or "ocultar-al-usuario" in s):
        marcar("envio-a-destino", 2, m)

    # Texto escondido tras muchas líneas o espacios en blanco (se mira el texto crudo).
    if (m := TRAS_ESPACIOS.search(visible(texto))) and (m.group(1) or m.group(2) or "").strip():
        marcar("texto-tras-espacios", 2)
        explicita = explicita or bool(m)

    vis = " ".join(visible(texto).split())
    pos_vis = len(" ".join(visible(texto)[:mapa[pos]].split())) if (pos is not None and mapa) else 0
    return {"puntaje": sum(s.values()), "senales": s, "explicita": explicita,
            "atenuada": bool(atenuado), "pos": pos_vis, "visible": vis}


def _categoria(r: dict) -> str:
    """Instrucción explícita salvo que solo haya redacción de recomendación sin marcas explícitas."""
    if r["explicita"]:
        return "tool-poisoning-instruccion"
    if r["atenuada"] or "dirigido-al-modelo" in r["senales"]:
        return "tool-poisoning-parafraseado"
    return "tool-poisoning-instruccion"


def _canal_sin_relacion(herramienta: dict) -> set[str]:
    """Parámetros con nombre de canal (contexto, notas...) opcionales, sin descripción y no mencionados."""
    params = parametros(herramienta)
    requeridos = set((herramienta.get("esquema") or {}).get("required") or [])
    desc = normalizar(herramienta.get("descripcion") or "")
    return {p for p, sub in params.items()
            if p.lower() in PARAM_CANAL and p not in requeridos and not sub.get("description")
            and p.lower() not in desc}


def analizar_herramienta(servidor: str, h: dict) -> list[dict]:
    salida = []
    nombres_param = set(parametros(h))
    canal = _canal_sin_relacion(h)
    for donde, texto in textos(h):
        lugar = "descripción" if donde in ("descripcion", "titulo") else f"parámetro {donde.split(':', 1)[1]}"
        ubic = ubicacion(h, donde)

        inv = invisibles(texto)
        if inv["tags"] or inv["ancho_cero"] or inv["direccion"]:
            partes = []
            if inv["tags"]:
                partes.append(f"{inv['n_tags']} caracteres tag que decodifican: «{inv['tags'].strip()}»")
            if inv["ancho_cero"]:
                partes.append(f"{len(inv['ancho_cero'])} de ancho cero")
            if inv["direccion"]:
                partes.append(f"{len(inv['direccion'])} de control de dirección")
            oculto = senales(inv["tags"]) if inv["tags"] else {"puntaje": 0}
            grave = inv["n_tags"] >= 3 or len(inv["ancho_cero"]) >= 3 or oculto["puntaje"] >= PUNTAJE_MINIMO
            salida.append(hallazgo(
                servidor=servidor, categoria="tool-poisoning-unicode",
                regla="unicode-tags" if inv["tags"] else ("unicode-ancho-cero" if inv["ancho_cero"]
                                                          else "unicode-direccion"),
                severidad="alta" if grave else "media",
                evidencia=f"[{h['nombre']} · {lugar}] " + "; ".join(partes),
                ubicacion=ubic))

        r = senales(texto, nombres_param)
        puntaje = r["puntaje"] + (1 if canal and r["puntaje"] else 0)
        if puntaje < PUNTAJE_MINIMO or not SENALES_INTENCION & set(r["senales"]):
            continue
        if canal and r["puntaje"]:
            r["senales"]["parametro-sin-relacion"] = 1
        principal = max(r["senales"], key=lambda k: (r["senales"][k], k))
        lista = ", ".join(f"{k}" for k in sorted(r["senales"], key=lambda k: -r["senales"][k]))
        salida.append(hallazgo(
            servidor=servidor, categoria=_categoria(r), regla=principal,
            severidad="alta" if puntaje >= PUNTAJE_ALTA else "media",
            evidencia=f"[{h['nombre']} · {lugar}] señales: {lista} | {_recortar(r['visible'], r['pos'])}",
            ubicacion=ubic))
    return salida


def analizar(dir_servidor: Path) -> list[dict]:
    dir_servidor = Path(dir_servidor)
    salida = []
    for h in cargar(dir_servidor):
        salida += analizar_herramienta(dir_servidor.name, h)
    return salida
