#!/usr/bin/env python3
"""Extrae las definiciones de herramientas (nombre, descripción y esquema) leyendo el código, SIN ejecutarlo.

Los servidores reales descargados de npm no traen herramientas.json. Este módulo lee el
JavaScript o TypeScript del paquete (también compilado o minificado) y reconstruye la lista
de herramientas con el mismo formato del corpus (docs/formatos.md). Reconoce:

- server.registerTool("nombre", { title, description, inputSchema }, handler)
- server.tool("nombre", "descripción", { esquema zod }, [anotaciones], handler)
- objetos { name, description, inputSchema | parameters | handler ... } (listas de ListTools,
  FastMCP addTool, defineTool, etc.)

Evalúa solo un subconjunto seguro de expresiones: textos, plantillas, concatenación, .join(),
constantes del mismo archivo o del paquete, objetos, listas y cadenas de zod (z.string().describe(...))
o TypeBox. Lo que no puede resolver queda como ${…} en el texto; nunca ejecuta nada.

Desde la raíz del repositorio:
    python -m frente_b_descripciones.extractor <corpus> [--forzar] [--resumen salida.json]

Escribe <servidor>/herramientas.json en cada servidor sin ese archivo (los del banco, con
fuente "local", nunca se tocan) e imprime qué porcentaje se pudo extraer.
"""
import argparse
import json
import re
import sys
import textwrap
from pathlib import Path

EXTENSIONES = {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx"}
CARPETAS_EXCLUIDAS = {"node_modules", "test", "tests", "__tests__", "__mocks__", ".git"}
MAX_ARCHIVO = 8 * 1024 * 1024
MARCADOR = "${…}"
ANCLAS = ("registerTool", ".tool(", "description", "addTool")

# ============================================================================ tokenizador

_ESPACIO = re.compile(r"\s+")
_COMENTARIO = re.compile(r"//[^\n]*|/\*.*?\*/|<!--[^\n]*|#![^\n]*", re.DOTALL)
_TEXTO = re.compile(r'"(?:[^"\\\n]|\\(?:.|\n))*"|\'(?:[^\'\\\n]|\\(?:.|\n))*\'')
_NUMERO = re.compile(r"0[xXbBoO][\da-fA-F_]+n?|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?n?")
_IDENT = re.compile(r"#?[A-Za-z_$\u0080-￿][\w$\u0080-￿]*")
_PUNT = re.compile(r">>>=|\.\.\.|===|!==|\*\*=|<<=|>>=|>>>|=>|==|!=|<=|>=|&&=|\|\|=|\?\?=|&&|\|\||\?\?|\?\.(?!\d)|"
                   r"\+\+|--|\+=|-=|\*=|/=|%=|&=|\|=|\^=|\*\*|<<|>>|[{}()\[\];,<>+\-*/%&|^!~?:=.@#]")
_ANTES_DE_REGEX = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do",
                   "else", "yield", "await", "export", "default"}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


class Tok:
    __slots__ = ("t", "v", "l")

    def __init__(self, t, v, l):
        self.t, self.v, self.l = t, v, l      # tipo: str, tpl, num, id, p, re

    def __repr__(self):
        return f"{self.t}:{self.v!r}"


def decodificar(cuerpo: str) -> str:
    """Interpreta los escapes de un texto de JavaScript (incluye \\u{...} y pares sustitutos)."""
    if "\\" not in cuerpo:
        return cuerpo
    out, i, n = [], 0, len(cuerpo)
    while i < n:
        c = cuerpo[i]
        if c != "\\" or i + 1 >= n:
            out.append(c); i += 1; continue
        e = cuerpo[i + 1]
        if e in _ESCAPES and not (e == "0" and i + 2 < n and cuerpo[i + 2].isdigit()):
            out.append(_ESCAPES[e]); i += 2
        elif e == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", cuerpo[i + 2:i + 4]):
            out.append(chr(int(cuerpo[i + 2:i + 4], 16))); i += 4
        elif e == "u" and cuerpo[i + 2:i + 3] == "{":
            fin = cuerpo.find("}", i + 3)
            try:
                out.append(chr(int(cuerpo[i + 3:fin], 16))); i = fin + 1
            except (ValueError, OverflowError):
                out.append(e); i += 2
        elif e == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", cuerpo[i + 2:i + 6]):
            out.append(chr(int(cuerpo[i + 2:i + 6], 16))); i += 6
        elif e == "\n":
            i += 2
        elif e == "\r":
            i += 3 if cuerpo[i + 2:i + 3] == "\n" else 2
        else:
            out.append(e); i += 2
    s = "".join(out)
    try:  # une pares sustitutos (󠁉 -> U+E0049)
        return s.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        return s


def tokenizar(src: str, pos: int = 0, linea: int = 1, hasta_llave: bool = False):
    """Devuelve (tokens, posición final, línea final). Con hasta_llave, para en la '}' que cierra un ${...}."""
    toks: list[Tok] = []
    n = len(src)
    profundidad = 0
    while pos < n:
        c = src[pos]
        if c.isspace():
            m = _ESPACIO.match(src, pos)
            linea += src.count("\n", pos, m.end()); pos = m.end(); continue
        if c == "/" and pos + 1 < n and src[pos + 1] in "/*":
            m = _COMENTARIO.match(src, pos)
            if m:
                linea += src.count("\n", pos, m.end()); pos = m.end(); continue
        if c in "\"'":
            m = _TEXTO.match(src, pos)
            if m:
                toks.append(Tok("str", decodificar(m.group()[1:-1]), linea))
                linea += m.group().count("\n"); pos = m.end(); continue
            toks.append(Tok("p", c, linea)); pos += 1; continue
        if c == "`":
            partes, pos, linea0 = [], pos + 1, linea
            buf = []
            while pos < n:
                ch = src[pos]
                if ch == "\\" and pos + 1 < n:
                    buf.append(src[pos:pos + 2]); linea += src[pos + 1] == "\n"; pos += 2
                elif ch == "`":
                    pos += 1; break
                elif ch == "$" and src.startswith("${", pos):
                    partes.append(decodificar("".join(buf))); buf = []
                    sub, pos, linea = tokenizar(src, pos + 2, linea, hasta_llave=True)
                    partes.append(sub)
                else:
                    buf.append(ch); linea += ch == "\n"; pos += 1
            partes.append(decodificar("".join(buf)))
            toks.append(Tok("tpl", partes, linea0)); continue
        if c == "/":
            prev = toks[-1] if toks else None
            es_regex = prev is None or (prev.t == "p" and prev.v not in (")", "]")) or \
                (prev.t == "id" and prev.v in _ANTES_DE_REGEX)
            if es_regex:
                j, en_clase = pos + 1, False
                while j < n and src[j] != "\n":
                    if src[j] == "\\":
                        j += 2; continue
                    if src[j] == "[":
                        en_clase = True
                    elif src[j] == "]":
                        en_clase = False
                    elif src[j] == "/" and not en_clase:
                        break
                    j += 1
                if j < n and src[j] == "/":
                    j += 1
                    while j < n and (src[j].isalnum() or src[j] == "_"):
                        j += 1
                    toks.append(Tok("re", src[pos:j], linea)); pos = j; continue
        if c.isdigit() or (c == "." and pos + 1 < n and src[pos + 1].isdigit()):
            m = _NUMERO.match(src, pos)
            toks.append(Tok("num", m.group(), linea)); pos = m.end(); continue
        m = _IDENT.match(src, pos)
        if m:
            toks.append(Tok("id", m.group(), linea)); pos = m.end(); continue
        m = _PUNT.match(src, pos)
        if m:
            v = m.group()
            if hasta_llave:
                if v == "{":
                    profundidad += 1
                elif v == "}":
                    if profundidad == 0:
                        return toks, m.end(), linea
                    profundidad -= 1
            toks.append(Tok("p", v, linea)); pos = m.end(); continue
        pos += 1  # carácter desconocido: se salta
    return toks, pos, linea


# ============================================================================ evaluador


class _Desconocido:
    """Valor que no se puede resolver sin ejecutar código. Guarda el identificador si lo hay."""
    __slots__ = ("nombre",)

    def __init__(self, nombre=None):
        self.nombre = nombre

    def __repr__(self):
        return f"<?{self.nombre or ''}>"


DESCONOCIDO = _Desconocido()
_ABRE = {"(": ")", "[": "]", "{": "}"}
_CIERRA = set(_ABRE.values())
_TIPOS_ZOD = {"string": "string", "number": "number", "bigint": "integer", "boolean": "boolean", "date": "string",
              "object": "object", "array": "array", "enum": "string", "nativeEnum": "string", "literal": None,
              "union": None, "discriminatedUnion": None, "any": None, "unknown": None, "record": "object",
              "tuple": "array", "null": "null", "int": "integer", "url": "string", "email": "string",
              "strictObject": "object", "looseObject": "object", "uuid": "string", "iso": "string",
              "instanceof": None, "lazy": None, "custom": None, "map": "object", "set": "array"}
_TIPOS_TYPEBOX = {"String": "string", "Number": "number", "Integer": "integer", "Boolean": "boolean",
                  "Object": "object", "Array": "array", "Union": None, "Literal": None, "Optional": None,
                  "Any": None, "Unknown": None, "Record": "object", "Enum": "string", "Null": "null"}
_METODOS_TEXTO = {"trim", "trimStart", "trimEnd", "trimLeft", "trimRight", "toString", "valueOf", "normalize"}
_FUNC_DEDENT = {"dedent", "outdent", "stripIndent", "stripIndents", "oneLine", "oneLineTrim", "unindent", "endent"}


def _texto(v) -> str | None:
    """Convierte un valor a texto (con ${…} en lo desconocido), o None si no tiene nada de texto."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v)
    return None


class Archivo:
    """Tokens de un archivo, pareo de corchetes y constantes declaradas."""

    def __init__(self, ruta: Path, rel: str, src: str):
        self.ruta, self.rel = ruta, rel
        self.toks, _, _ = tokenizar(src)
        n = len(self.toks)
        self.par = [-1] * n            # índice del corchete que cierra o abre
        self.padre = [-1] * n          # índice del '{' que encierra a cada token
        pila: list[int] = []
        for i, t in enumerate(self.toks):
            if pila and self.toks[pila[-1]].v == "{":
                self.padre[i] = pila[-1]
            if t.t == "p" and t.v in _ABRE:
                pila.append(i)
            elif t.t == "p" and t.v in _CIERRA:
                while pila and _ABRE[self.toks[pila[-1]].v] != t.v:
                    pila.pop()  # corchetes desbalanceados (TS, regex mal leídas): se recupera
                if pila:
                    j = pila.pop()
                    self.par[i], self.par[j] = j, i
        self.constantes: dict[str, list[tuple[int, int]]] = {}
        for i, t in enumerate(self.toks):
            if t.t == "id" and t.v in ("const", "let", "var") and i + 2 < n and self.toks[i + 1].t == "id":
                j = i + 2
                if self.toks[j].t == "p" and self.toks[j].v == ":":     # anotación de tipo de TypeScript
                    while j < n and not (self.toks[j].t == "p" and self.toks[j].v in ("=", ";", ",")):
                        j = self.par[j] + 1 if self.toks[j].t == "p" and self.toks[j].v in _ABRE and self.par[j] > 0 else j + 1
                if j < n and self.toks[j].t == "p" and self.toks[j].v == "=":
                    self.constantes.setdefault(self.toks[i + 1].v, []).append((j + 1, self.fin_expr(j + 1)))

    def fin_expr(self, i: int, limite: int | None = None) -> int:
        """Índice donde termina la expresión que empieza en i (',' ';' o corchete de cierre al nivel 0)."""
        n = len(self.toks) if limite is None else limite
        while i < n:
            t = self.toks[i]
            if t.t == "p":
                if t.v in _ABRE:
                    if self.par[i] < 0:
                        return n
                    i = self.par[i] + 1; continue
                if t.v in _CIERRA or t.v in (",", ";"):
                    return i
            i += 1
        return n

    def argumentos(self, abre: int) -> list[tuple[int, int]]:
        cierra = self.par[abre]
        if cierra < 0:
            return []
        args, i = [], abre + 1
        while i < cierra:
            fin = self.fin_expr(i, cierra)
            if fin > i:
                args.append((i, fin))
            i = fin + 1
        return args


class Evaluador:
    def __init__(self, paquete: "Paquete", archivo: Archivo, padre: "Evaluador | None" = None):
        self.paquete, self.a = paquete, archivo
        self.padre = padre     # para ${...}: las constantes se buscan en el archivo que contiene la plantilla
        self.pila: set = set()

    # ---------------------------------------------------------------- valores
    def constante(self, nombre: str):
        """Valor de una constante del archivo; si no está, una del paquete con nombre único."""
        if self.padre is not None:
            return self.padre.constante(nombre)
        decl = self.a.constantes.get(nombre)
        archivo = self.a
        if not decl:
            fuera = self.paquete.constante_global(nombre)
            if not fuera:
                return _Desconocido(nombre)
            archivo, decl = fuera
        if len(decl) != 1 or (archivo.rel, nombre) in self.pila or len(self.pila) > 12:
            return _Desconocido(nombre)
        self.pila.add((archivo.rel, nombre))
        try:
            ev = self if archivo is self.a else Evaluador(self.paquete, archivo)
            ev.pila = self.pila
            return ev.valor(*decl[0])
        finally:
            self.pila.discard((archivo.rel, nombre))

    def valor(self, a: int, b: int):
        toks = self.a.toks
        # Quita anotaciones de TypeScript al final: `as const`, `satisfies T`, `!`.
        i = a
        while i < b:
            t = toks[i]
            if t.t == "p" and t.v in _ABRE and self.a.par[i] > 0:
                i = self.a.par[i] + 1; continue
            if t.t == "id" and t.v in ("as", "satisfies") and i > a and not (
                    toks[i - 1].t == "p" and toks[i - 1].v in (".", "?.")):
                b = i; break
            i += 1
        while b > a and toks[b - 1].t == "p" and toks[b - 1].v == "!":
            b -= 1
        while a < b and toks[a].t == "id" and toks[a].v in ("await", "void", "new"):
            a += 1
        if a >= b:
            return DESCONOCIDO
        # Operadores binarios al nivel 0: ternario, ||/??, +.
        partes, alternativas, i, ini = [], [], a, a
        while i < b:
            t = toks[i]
            if t.t == "p":
                if t.v in _ABRE and self.a.par[i] > 0:
                    i = self.a.par[i] + 1; continue
                if t.v == "?" or t.v == "=>":
                    return DESCONOCIDO
                if t.v in ("||", "??"):
                    alternativas.append((ini, i)); ini = i + 1
                elif t.v == "+" and i > ini:
                    partes.append((ini, i)); ini = i + 1
            i += 1
        if alternativas:
            alternativas.append((ini, b))
            vals = [self.valor(x, y) for x, y in alternativas]
            for v in reversed(vals):        # `process.env.X || "texto por defecto"`
                if _texto(v) is not None:
                    return v
            return DESCONOCIDO
        if partes:
            partes.append((ini, b))
            vals = [self.valor(x, y) for x, y in partes]
            textos = [_texto(v) for v in vals]
            if not any(isinstance(v, str) for v in vals):
                return DESCONOCIDO
            return "".join(t if t is not None else MARCADOR for t in textos)
        return self.cadena(a, b)

    def plantilla(self, tok: Tok) -> str:
        out = []
        for p in tok.v:
            if isinstance(p, str):
                out.append(p)
            else:
                sub = Archivo.__new__(Archivo)  # evalúa la expresión ${...} con los mismos datos
                sub.ruta, sub.rel, sub.toks = self.a.ruta, self.a.rel, p
                sub.constantes = {}
                sub.par, sub.padre = _parear(p), [-1] * len(p)
                v = Evaluador(self.paquete, sub, padre=self).valor(0, len(p)) if p else DESCONOCIDO
                t = _texto(v)
                out.append(t if t is not None else MARCADOR)
        return "".join(out)

    def primario(self, i: int, b: int):
        """Devuelve (valor, siguiente índice)."""
        toks, t = self.a.toks, self.a.toks[i]
        if t.t == "str":
            return t.v, i + 1
        if t.t == "tpl":
            return self.plantilla(t), i + 1
        if t.t == "num":
            try:
                return float(t.v.replace("_", "").rstrip("n")) if "." in t.v or "e" in t.v.lower() and not t.v.startswith("0x") \
                    else int(t.v.replace("_", "").rstrip("n"), 0), i + 1
            except ValueError:
                return DESCONOCIDO, i + 1
        if t.t == "p" and t.v == "-" and i + 1 < b and toks[i + 1].t == "num":
            v, j = self.primario(i + 1, b)
            return (-v if isinstance(v, (int, float)) else DESCONOCIDO), j
        if t.t == "p" and t.v == "!" and i + 1 < b and toks[i + 1].t == "num":   # minificado: !0 / !1
            return toks[i + 1].v == "0", i + 2
        if t.t == "p" and t.v == "{":
            return self.objeto(i), self.a.par[i] + 1 if self.a.par[i] > 0 else b
        if t.t == "p" and t.v == "[":
            fin = self.a.par[i]
            if fin < 0:
                return DESCONOCIDO, b
            return [self.valor(x, y) for x, y in self.a.argumentos(i)], fin + 1
        if t.t == "p" and t.v == "(":
            fin = self.a.par[i]
            if fin < 0:
                return DESCONOCIDO, b
            if fin + 1 < b and toks[fin + 1].t == "p" and toks[fin + 1].v == "=>":
                return DESCONOCIDO, b
            return self.valor(i + 1, fin), fin + 1
        if t.t == "id":
            if t.v in ("true", "false"):
                return t.v == "true", i + 1
            if t.v in ("null", "undefined"):
                return None, i + 1
            if t.v in ("function", "async", "class"):
                return DESCONOCIDO, b
            if i + 1 < b and toks[i + 1].t == "tpl":           # plantilla con etiqueta: dedent`...`
                texto = self.plantilla(toks[i + 1])
                if t.v in _FUNC_DEDENT:
                    texto = textwrap.dedent(texto).strip()
                return texto, i + 2
            return _Ref(t.v, self), i + 1
        return DESCONOCIDO, b

    def cadena(self, a: int, b: int):
        """Primario seguido de accesos y llamadas: x.y, x["y"], f(...), z.string().describe(...)."""
        toks = self.a.toks
        v, i = self.primario(a, b)
        while i < b:
            t = toks[i]
            if t.t == "p" and t.v in (".", "?.") and i + 1 < b and toks[i + 1].t == "id":
                nombre = toks[i + 1].v
                j = i + 2
                if j < b and toks[j].t == "p" and toks[j].v == "(" and self.a.par[j] > 0:
                    args = self.a.argumentos(j)
                    v = self.metodo(v, nombre, args)
                    i = self.a.par[j] + 1
                else:
                    v = self.miembro(v, nombre)
                    i = j
                continue
            if t.t == "p" and t.v == "[" and self.a.par[i] > 0:
                clave = self.valor(i + 1, self.a.par[i])
                v = self.miembro(v, clave) if isinstance(clave, (str, int)) else DESCONOCIDO
                i = self.a.par[i] + 1
                continue
            if t.t == "p" and t.v == "(" and self.a.par[i] > 0:
                v = self.llamada(v, self.a.argumentos(i))
                i = self.a.par[i] + 1
                continue
            if t.t == "tpl":
                v = self.plantilla(t) if isinstance(v, _Ref) and v.nombre in _FUNC_DEDENT else DESCONOCIDO
                i += 1
                continue
            if t.t == "p" and t.v == "!":
                i += 1
                continue
            return DESCONOCIDO
        return _resolver(v)

    def miembro(self, v, nombre):
        if isinstance(v, _Ref):
            return _Ref(v.nombre + "." + str(nombre), v.ev, base=v)
        v = _resolver(v)
        if isinstance(v, dict) and not v.get("_zod"):
            return v.get(nombre, DESCONOCIDO) if isinstance(nombre, str) else DESCONOCIDO
        if isinstance(v, list) and isinstance(nombre, int) and -len(v) <= nombre < len(v):
            return v[nombre]
        if isinstance(v, (dict, list, str)) and nombre == "length":
            return len(v)
        return DESCONOCIDO

    def metodo(self, v, nombre: str, args):
        vals = lambda: [self.valor(x, y) for x, y in args]
        # Constructores de zod (z.string()) y TypeBox (Type.String()) sobre cualquier identificador.
        if isinstance(v, _Ref):
            base = v.nombre.split(".")[-1]
            if nombre in _TIPOS_ZOD and base not in ("Object", "JSON", "Array", "String", "Math", "console", "Type"):
                return self.zod(nombre, args)
            if nombre in _TIPOS_TYPEBOX and base in ("Type", "t", "T", "Typebox"):
                return self.typebox(nombre, args)
            if nombre in ("freeze", "assign") and base == "Object":
                vs = vals()
                if nombre == "freeze" and vs:
                    return vs[0]
                out = {}
                for x in vs:
                    if isinstance(x, dict):
                        out.update(x)
                return out
            v = _resolver(v)
        if isinstance(v, dict) and v.get("_zod"):
            return self.zod_metodo(v, nombre, args)
        if isinstance(v, str):
            if nombre in _METODOS_TEXTO:
                return v.strip() if nombre.startswith("trim") else v
            if nombre == "concat":
                return v + "".join(_texto(x) or MARCADOR for x in vals())
            if nombre == "replace" or nombre == "replaceAll":
                vs = vals()
                if len(vs) == 2 and isinstance(vs[0], str) and isinstance(vs[1], str):
                    return v.replace(vs[0], vs[1]) if nombre == "replaceAll" else v.replace(vs[0], vs[1], 1)
                return v
            return DESCONOCIDO
        if isinstance(v, list):
            if nombre == "join":
                vs = vals()
                sep = vs[0] if vs and isinstance(vs[0], str) else ","
                textos = [_texto(x) for x in v]
                if not any(isinstance(x, str) for x in v):
                    return DESCONOCIDO
                return sep.join(t if t is not None else MARCADOR for t in textos)
            if nombre in ("filter", "map", "flat", "concat", "slice"):
                return DESCONOCIDO
        return DESCONOCIDO

    def llamada(self, v, args):
        if isinstance(v, _Ref) and v.nombre in _FUNC_DEDENT and args:
            x = self.valor(*args[0])
            return textwrap.dedent(x).strip() if isinstance(x, str) else DESCONOCIDO
        if isinstance(v, _Ref) and v.nombre in ("String",) and args:
            x = self.valor(*args[0])
            return _texto(x) if _texto(x) is not None else DESCONOCIDO
        return DESCONOCIDO

    def objeto(self, abre: int) -> dict:
        out: dict = {}
        toks = self.a.toks
        for x, y in self.a.argumentos(abre):
            t = toks[x]
            if t.t == "p" and t.v == "...":
                extra = _resolver(self.valor(x + 1, y))
                if isinstance(extra, dict) and not extra.get("_zod"):
                    out.update(extra)
                continue
            # get/set/async/* antes del nombre de un método
            k = x
            while k + 1 < y and ((toks[k].t == "p" and toks[k].v == "*") or (
                    toks[k].t == "id" and toks[k].v in ("async", "get", "set", "static") and toks[k + 1].t in ("id", "str"))):
                k += 1
            clave = None
            if toks[k].t in ("id", "str", "num"):
                clave, k = str(toks[k].v), k + 1
            elif toks[k].t == "p" and toks[k].v == "[" and self.a.par[k] > 0:
                c = self.valor(k + 1, self.a.par[k])
                clave = c if isinstance(c, str) else None
                k = self.a.par[k] + 1
            if clave is None:
                continue
            if k >= y:                                   # forma abreviada { description }
                out[clave] = _resolver(_Ref(clave, self))
            elif toks[k].t == "p" and toks[k].v == ":":
                out[clave] = self.valor(k + 1, y)
            elif toks[k].t == "p" and toks[k].v in ("(", "?", "<"):
                out[clave] = DESCONOCIDO                 # método
        return out

    # ---------------------------------------------------------------- zod y TypeBox
    def zod(self, tipo: str, args) -> dict:
        esquema = {"_zod": True}
        if _TIPOS_ZOD.get(tipo):
            esquema["type"] = _TIPOS_ZOD[tipo]
        vals = [self.valor(x, y) for x, y in args]
        if tipo in ("object", "strictObject", "looseObject") and vals:
            forma = vals[0]
            if isinstance(forma, dict) and not forma.get("_zod"):
                esquema.update(_desde_forma(forma))
        elif tipo == "array" and vals and isinstance(vals[0], dict):
            esquema["items"] = limpiar_esquema(vals[0])
        elif tipo == "enum" and vals and isinstance(vals[0], list):
            esquema["enum"] = [x for x in vals[0] if isinstance(x, (str, int, float))]
        elif tipo == "literal" and vals and isinstance(vals[0], (str, int, float, bool)):
            esquema["const"] = vals[0]
        elif tipo in ("union", "discriminatedUnion") and vals:
            opciones = vals[-1] if isinstance(vals[-1], list) else []
            esquema["anyOf"] = [limpiar_esquema(o) for o in opciones if isinstance(o, dict)]
        # zod 4: z.string({ description: "..." }) o z.object(forma, { description: "..." })
        opciones = vals[1] if tipo in ("object", "strictObject", "looseObject", "array", "record") and len(vals) > 1 \
            else (vals[0] if vals and tipo not in ("object", "strictObject", "looseObject", "array", "record") else None)
        if isinstance(opciones, dict) and not opciones.get("_zod") and isinstance(opciones.get("description"), str):
            esquema["description"] = opciones["description"]
        return esquema

    def zod_metodo(self, esquema: dict, nombre: str, args) -> dict:
        esquema = dict(esquema)
        vals = [self.valor(x, y) for x, y in args]
        if nombre == "describe" and vals:
            t = _texto(vals[0])
            esquema["description"] = t if t is not None else MARCADOR
        elif nombre == "meta" and vals and isinstance(vals[0], dict):
            if isinstance(vals[0].get("description"), str):
                esquema["description"] = vals[0]["description"]
            if isinstance(vals[0].get("title"), str):
                esquema["title"] = vals[0]["title"]
        elif nombre in ("optional", "nullish", "default", "catch"):
            esquema["_opcional"] = True
        elif nombre == "array":
            return {"_zod": True, "type": "array", "items": limpiar_esquema(esquema)}
        elif nombre in ("extend", "merge", "safeExtend") and vals and isinstance(vals[0], dict):
            extra = vals[0] if not vals[0].get("_zod") else {k: v for k, v in
                                                            vals[0].get("properties", {}).items()}
            forma = _desde_forma(extra) if not vals[0].get("_zod") else {
                "properties": extra, "required": vals[0].get("required", [])}
            esquema.setdefault("properties", {}).update(forma.get("properties", {}))
            esquema["required"] = sorted(set(esquema.get("required", [])) | set(forma.get("required", [])))
        elif nombre in ("partial",):
            esquema.pop("required", None)
        return esquema

    def typebox(self, tipo: str, args) -> dict:
        esquema = {"_zod": True}
        if _TIPOS_TYPEBOX.get(tipo):
            esquema["type"] = _TIPOS_TYPEBOX[tipo]
        vals = [self.valor(x, y) for x, y in args]
        if tipo == "Object" and vals and isinstance(vals[0], dict):
            esquema.update(_desde_forma(vals[0]))
        elif tipo == "Array" and vals and isinstance(vals[0], dict):
            esquema["items"] = limpiar_esquema(vals[0])
        elif tipo == "Optional" and vals and isinstance(vals[0], dict):
            esquema = dict(vals[0]); esquema["_opcional"] = True
        opciones = vals[-1] if vals and isinstance(vals[-1], dict) and not vals[-1].get("_zod") else {}
        if tipo == "Object" and len(vals) < 2:
            opciones = {}
        if isinstance(opciones.get("description"), str):
            esquema["description"] = opciones["description"]
        return esquema


class _Ref:
    """Identificador todavía sin resolver (puede ser la base de z.string() o una constante)."""
    __slots__ = ("nombre", "ev", "base")

    def __init__(self, nombre, ev, base=None):
        self.nombre, self.ev, self.base = nombre, ev, base


def _resolver(v):
    if not isinstance(v, _Ref):
        return v
    partes = v.nombre.split(".")
    valor = v.ev.constante(partes[0])
    for p in partes[1:]:
        if isinstance(valor, dict) and not valor.get("_zod"):
            valor = valor.get(p, DESCONOCIDO)
        else:
            return _Desconocido(v.nombre)
    return valor


def _parear(toks: list[Tok]) -> list[int]:
    par, pila = [-1] * len(toks), []
    for i, t in enumerate(toks):
        if t.t == "p" and t.v in _ABRE:
            pila.append(i)
        elif t.t == "p" and t.v in _CIERRA and pila:
            j = pila.pop()
            par[i], par[j] = j, i
    return par


def _desde_forma(forma: dict) -> dict:
    """Forma de zod ({ a: z.string() }) a JSON Schema de objeto."""
    props, requeridos = {}, []
    for k, v in forma.items():
        if isinstance(v, dict):
            props[k] = limpiar_esquema(v)
            if not v.get("_opcional"):
                requeridos.append(k)
        else:
            props[k] = {}
    out = {"type": "object", "properties": props}
    if requeridos:
        out["required"] = requeridos
    return out


def limpiar_esquema(v):
    """Quita marcas internas y valores desconocidos para que el esquema sea JSON válido."""
    if isinstance(v, dict):
        return {k: limpiar_esquema(x) for k, x in v.items()
                if not k.startswith("_") and not isinstance(x, (_Desconocido, _Ref))}
    if isinstance(v, list):
        return [limpiar_esquema(x) for x in v if not isinstance(x, (_Desconocido, _Ref))]
    return v


def _a_esquema(v) -> dict:
    """inputSchema puede ser JSON Schema, una forma de zod o un z.object(...)."""
    v = _resolver(v)
    if not isinstance(v, dict):
        return {}
    if v.get("_zod"):
        return limpiar_esquema(v)
    if "type" in v or "properties" in v or "$schema" in v or "anyOf" in v or "oneOf" in v:
        return limpiar_esquema(v)
    return _desde_forma(v)


# ============================================================================ paquete


class Paquete:
    def __init__(self, dir_servidor: Path):
        self.dir = Path(dir_servidor)
        self.archivos: list[Archivo] = []
        self.globales: dict[str, list[tuple[Archivo, list]]] = {}
        codigo = self.dir / "codigo"
        if not codigo.is_dir():
            return
        for f in sorted(codigo.rglob("*")):
            if not f.is_file() or f.suffix not in EXTENSIONES or f.name.endswith(".d.ts"):
                continue
            rel_partes = f.relative_to(codigo).parts
            if CARPETAS_EXCLUIDAS & set(rel_partes) or re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", f.name):
                continue
            try:
                if f.stat().st_size > MAX_ARCHIVO:
                    continue
                src = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not any(a in src for a in ANCLAS) and not re.search(r"\bexport\s+(const|let|var)\b", src):
                continue
            arch = Archivo(f, "codigo/" + "/".join(rel_partes), src)
            self.archivos.append(arch)
            for nombre, decl in arch.constantes.items():
                if len(nombre) > 2:  # en código minificado los nombres cortos se repiten
                    self.globales.setdefault(nombre, []).append((arch, decl))

    def constante_global(self, nombre: str):
        opciones = self.globales.get(nombre, [])
        if len(opciones) == 1:
            return opciones[0]
        return None


_NOMBRE_VALIDO = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-/:]{0,127}$")
_CLAVES_ESQUEMA = ("inputSchema", "input_schema", "parameters", "paramsSchema", "argsSchema", "schema", "args",
                   "inputSchemaZod", "input")
_CLAVES_HANDLER = ("handler", "execute", "run", "cb", "callback", "fn", "invoke", "call", "action", "impl")


def _tool(nombre, descripcion, esquema, archivo: Archivo, tok: Tok, patron: str, titulo=None) -> dict | None:
    nombre = _resolver(nombre)
    if not isinstance(nombre, str) or not _NOMBRE_VALIDO.match(nombre):
        return None
    d = _resolver(descripcion)
    texto = _texto(d)
    if texto is None and isinstance(d, dict) and d.get("_zod"):
        texto = None
    h = {"nombre": nombre, "descripcion": texto if texto is not None else (MARCADOR if descripcion is not None else ""),
         "esquema": _a_esquema(esquema) if esquema is not None else {"type": "object", "properties": {}},
         "origen": f"{archivo.rel}:{tok.l}", "patron": patron}
    if isinstance(_resolver(titulo), str):
        h["titulo"] = _resolver(titulo)
    if not h["esquema"]:
        h["esquema"] = {"type": "object", "properties": {}}
    return h


def _claves(a: Archivo, abre: int) -> set[str]:
    """Claves del nivel superior de un objeto literal."""
    toks, n = a.toks, len(a.toks)
    return {toks[x].v for x, _ in a.argumentos(abre)
            if toks[x].t in ("id", "str") and x + 1 < n and toks[x + 1].t == "p" and toks[x + 1].v in (":", ",", "}", "(")}


def _extraer_archivo(paquete: Paquete, a: Archivo) -> list[dict]:
    ev = Evaluador(paquete, a)
    toks, n = a.toks, len(a.toks)
    salida, objetos_vistos = [], set()
    for i, t in enumerate(toks):
        if t.t != "id":
            continue
        sig = toks[i + 1] if i + 1 < n else None
        if sig is None:
            break
        # --- registerTool(nombre, { description, inputSchema, title }, handler)
        if t.v == "registerTool" and sig.t == "p" and sig.v == "(":
            cierra = a.par[i + 1]
            if cierra < 0 or (cierra + 1 < n and toks[cierra + 1].t == "p" and toks[cierra + 1].v == "{"):
                continue  # definición del método, no una llamada
            args = a.argumentos(i + 1)
            if len(args) < 2:
                continue
            config = ev.valor(*args[1])
            config = config if isinstance(config, dict) else {}
            h = _tool(ev.valor(*args[0]), config.get("description"),
                      config.get("inputSchema", config.get("paramsSchema")), a, t, "registerTool",
                      titulo=config.get("title"))
            if h:
                salida.append(h)
        # --- server.tool(nombre, [descripción], [esquema], [anotaciones], handler)
        elif t.v == "tool" and i > 0 and toks[i - 1].t == "p" and toks[i - 1].v in (".", "?.") and \
                sig.t == "p" and sig.v == "(":
            args = a.argumentos(i + 1)
            if len(args) < 2:
                continue
            nombre = ev.valor(*args[0])
            if not isinstance(_resolver(nombre), str):
                continue
            descripcion, esquema = None, None
            for x, y in args[1:-1]:
                v = _resolver(ev.valor(x, y))
                if descripcion is None and esquema is None and isinstance(v, str):
                    descripcion = v
                elif esquema is None and (isinstance(v, dict) or isinstance(v, _Desconocido)):
                    esquema = v if isinstance(v, dict) else {}
                    if isinstance(v, dict) and not v.get("_zod") and v and all(
                            k.endswith("Hint") or k == "title" for k in v):
                        esquema = {}  # eran anotaciones, no esquema
                        break
            h = _tool(nombre, descripcion, esquema, a, t, "server.tool")
            if h:
                salida.append(h)
        # --- envoltorio propio: reg("nombre", { description, inputSchema }, handler)
        elif sig.t == "p" and sig.v == "(" and t.v not in ("registerTool", "tool") and i + 3 < n and \
                toks[i + 2].t in ("str", "tpl") and toks[i + 3].t == "p" and toks[i + 3].v == "," and \
                i + 4 < n and toks[i + 4].t == "p" and toks[i + 4].v == "{" and a.par[i + 4] > 0:
            claves = _claves(a, i + 4)
            if "description" in claves and claves & set(_CLAVES_ESQUEMA):
                config = ev.objeto(i + 4)
                esquema = next((config[k] for k in _CLAVES_ESQUEMA if k in config), None)
                h = _tool(ev.valor(i + 2, i + 3), config.get("description"), esquema, a, t, "envoltorio",
                          titulo=config.get("title"))
                if h:
                    salida.append(h)
        # --- objeto { name: "...", description: ..., inputSchema | handler ... }
        elif t.v == "name" and sig.t == "p" and sig.v == ":":
            abre = a.padre[i]
            if abre < 0 or abre in objetos_vistos:
                continue
            objetos_vistos.add(abre)
            claves = _claves(a, abre)
            if "description" not in claves or "uri" in claves or "mimeType" in claves:
                continue
            if not (claves & set(_CLAVES_ESQUEMA) or claves & set(_CLAVES_HANDLER)):
                continue
            obj = ev.objeto(abre)
            esquema = next((obj[k] for k in _CLAVES_ESQUEMA if k in obj), None)
            h = _tool(obj.get("name"), obj.get("description"), esquema, a, toks[abre], "objeto",
                      titulo=obj.get("title"))
            if h:
                salida.append(h)
    return salida


def _sin_marcadores(s: str) -> str:
    return " ".join(s.replace(MARCADOR, " ").split())


def _deduplicar(herramientas: list[dict]) -> list[dict]:
    """Quita repeticiones (src y dist, ESM y CJS). Variantes con texto distinto se conservan."""
    por_nombre: dict[str, list[dict]] = {}
    for h in herramientas:
        por_nombre.setdefault(h["nombre"], []).append(h)
    salida = []
    for nombre, variantes in por_nombre.items():
        # Primero las más completas: menos marcadores y descripción más larga.
        variantes.sort(key=lambda h: (h["descripcion"].count(MARCADOR), -len(_sin_marcadores(h["descripcion"])),
                                      -len(json.dumps(h["esquema"]))))
        elegidas: list[dict] = []
        for h in variantes:
            texto = _sin_marcadores(h["descripcion"])
            if any(texto in _sin_marcadores(e["descripcion"]) and
                   json.dumps(h["esquema"], sort_keys=True) in (json.dumps(e["esquema"], sort_keys=True), '{"properties": {}, "type": "object"}')
                   for e in elegidas):
                continue
            elegidas.append(h)
        salida += elegidas
    return salida


def _mapa_de_descripciones(paquete: Paquete, herramientas: list[dict]) -> None:
    """Completa descripciones vacías desde un objeto { nombre_herramienta: "descripción", ... }.

    Algunos servidores guardan las descripciones en un solo archivo y las aplican con un envoltorio.
    Solo se usa un objeto que tenga como claves al menos dos herramientas sin descripción (o la única).
    """
    faltan = {h["nombre"] for h in herramientas if not _sin_marcadores(h["descripcion"])}
    if not faltan:
        return
    for a in paquete.archivos:
        candidatos: dict[int, int] = {}
        for i, t in enumerate(a.toks[:-1]):
            if t.t in ("id", "str") and t.v in faltan and a.toks[i + 1].t == "p" and a.toks[i + 1].v == ":" \
                    and a.padre[i] >= 0:
                candidatos[a.padre[i]] = candidatos.get(a.padre[i], 0) + 1
        for abre, cuantos in candidatos.items():
            if cuantos < min(2, len(faltan)):
                continue
            mapa = Evaluador(paquete, a).objeto(abre)
            for h in herramientas:
                texto = _texto(_resolver(mapa.get(h["nombre"])))
                if h["nombre"] in faltan and texto and _sin_marcadores(texto):
                    h["descripcion"] = texto
                    h["patron"] += "+mapa"


def extraer(dir_servidor: Path) -> list[dict]:
    """Lista de herramientas (formato de herramientas.json, con 'origen' y 'patron') leídas del código."""
    paquete = Paquete(dir_servidor)
    todas = []
    for a in paquete.archivos:
        try:
            todas += _extraer_archivo(paquete, a)
        except RecursionError:
            continue
    herramientas = _deduplicar(todas)
    try:
        _mapa_de_descripciones(paquete, herramientas)
    except RecursionError:
        pass
    return herramientas


def estado(h: dict) -> str:
    """'completa', 'parcial' (con partes ${…} que dependen de código) o 'sin descripcion'."""
    if not _sin_marcadores(h["descripcion"]):
        return "sin descripcion"
    return "parcial" if MARCADOR in h["descripcion"] else "completa"


# ============================================================================ CLI


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("corpus")
    ap.add_argument("--forzar", action="store_true", help="reescribe herramientas.json ya extraídos antes")
    ap.add_argument("--resumen", help="guarda el resumen de la extracción en este JSON")
    a = ap.parse_args()

    filas = []
    servidores = sorted(p for p in Path(a.corpus).iterdir() if p.is_dir() and (p / "manifest.json").exists())
    for d in servidores:
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        destino = d / "herramientas.json"
        if manifest.get("fuente") == "local":
            continue  # banco de pruebas: herramientas.json escrito a mano por el generador
        if destino.exists() and not a.forzar:
            previas = json.loads(destino.read_text(encoding="utf-8"))
            if not all("origen" in h for h in previas):
                continue  # no lo escribió el extractor: no se toca
        hs = extraer(d)
        if hs or destino.exists():
            destino.write_text(json.dumps(hs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        patrones = sorted({h["patron"].split("+")[0] for h in hs})
        estados = [estado(h) for h in hs]
        filas.append({"servidor": d.name, "herramientas": len(hs), "completas": estados.count("completa"),
                      "parciales": estados.count("parcial"), "sin_descripcion": estados.count("sin descripcion"),
                      "parametros_con_descripcion": sum(
                          1 for h in hs for p in (h["esquema"].get("properties") or {}).values()
                          if isinstance(p, dict) and p.get("description")),
                      "patrones": patrones})
        print(f"  {d.name}: {len(hs)} herramientas ({filas[-1]['completas']} completas, "
              f"{filas[-1]['parciales']} parciales)" + (f" [{', '.join(patrones)}]" if patrones else ""))

    if not filas:
        sys.exit("No hay servidores para extraer (¿corpus vacío o solo el banco de pruebas?).")
    con = [f for f in filas if f["herramientas"]]
    total = sum(f["herramientas"] for f in filas)
    comp = sum(f["completas"] for f in filas)
    parc = sum(f["parciales"] for f in filas)
    pct = lambda x, de: round(100 * x / de, 1) if de else None
    resumen = {
        "servidores": len(filas),
        "servidores_con_herramientas": len(con),
        "porcentaje_servidores": pct(len(con), len(filas)),
        "herramientas": total,
        "descripcion_completa": comp,
        "descripcion_parcial": parc,
        "sin_descripcion": total - comp - parc,
        "porcentaje_completa": pct(comp, total),
        "porcentaje_con_texto": pct(comp + parc, total),
        "por_patron": {p: sum(1 for f in filas if p in f["patrones"])
                       for p in ("registerTool", "server.tool", "envoltorio", "objeto")},
        "detalle": filas,
    }
    print(f"\n{len(con)} de {len(filas)} servidores con herramientas extraídas ({resumen['porcentaje_servidores']} %); "
          f"{total} herramientas: {comp} con la descripción completa ({resumen['porcentaje_completa']} %), "
          f"{parc} parcial y {resumen['sin_descripcion']} sin descripción.")
    print("Servidores por patrón:", resumen["por_patron"])
    if a.resumen:
        Path(a.resumen).parent.mkdir(parents=True, exist_ok=True)
        Path(a.resumen).write_text(json.dumps(resumen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                   newline="\n")


if __name__ == "__main__":
    main()
