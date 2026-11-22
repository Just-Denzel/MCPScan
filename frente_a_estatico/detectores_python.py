"""Detectores en Python para el Frente A.

Cubre categorías que Semgrep no maneja bien o que aplican a archivos no-JS/TS:
- script-instalacion (package.json)
- dependencia-typosquat (package.json)
- secreto-hardcodeado (cualquier archivo de texto del paquete)
"""
import json
import re
from pathlib import Path

from comun.formatos import hallazgo

# --- 1. Scripts de instalación ---

HOOKS_INSTALACION = ("preinstall", "install", "postinstall")

PATRON_SCRIPT_ALTO_RIESGO = re.compile(
    r"(?i)("
    r"\b(?:curl|wget|powershell|pwsh|iwr|invoke-webrequest)\b|"
    r"https?://|"
    r"\|\s*(?:ba)?sh\b|"
    r"\b(?:ba)?sh\s+-c\b|"
    r"\bnode\s+-e\b|"
    r"\bpython3?\s+-c\b|"
    r"\bbase64\b|"
    r"\beval\b|"
    r"process\.env|\.ssh|\.aws|/etc/passwd"
    r")"
)

# --- 2. Typosquatting de dependencias ---

# Paquetes muy descargados de npm + ecosistema MCP.
# Cualquier dependencia exactamente igual a uno de estos NO se marca.
PAQUETES_POPULARES = {
    # Ecosistema MCP / IA
    "@modelcontextprotocol/sdk", "openai", "@anthropic-ai/sdk", "langchain",
    "zod", "zod-to-json-schema", "ajv",
    # Utilidades y HTTP
    "lodash", "underscore", "ramda", "axios", "node-fetch", "undici", "got",
    "superagent", "request", "needle", "cross-fetch", "isomorphic-fetch",
    # Servidores y frameworks web
    "express", "fastify", "koa", "hono", "next", "nuxt", "react", "react-dom",
    "preact", "vue", "svelte", "angular", "cors", "helmet", "morgan",
    "body-parser", "cookie-parser", "compression", "multer", "socket.io",
    # CLI, archivos y sistema
    "chalk", "picocolors", "colorette", "commander", "yargs", "minimist",
    "inquirer", "prompts", "dotenv", "dotenv-expand", "fs-extra", "rimraf",
    "glob", "globby", "chokidar", "execa", "cross-env", "semver", "debug",
    "winston", "pino", "uuid", "nanoid", "ulid", "moment", "dayjs", "date-fns",
    "luxon", "mime", "mime-types", "form-data", "yaml", "js-yaml", "toml",
    "tar", "archiver", "adm-zip", "unzipper", "lru-cache", "p-limit",
    # Seguridad, auth y bases de datos
    "jsonwebtoken", "jose", "bcrypt", "bcryptjs", "argon2", "crypto-js",
    "mongoose", "prisma", "@prisma/client", "sequelize", "typeorm", "knex",
    "mysql", "mysql2", "sqlite3", "better-sqlite3", "redis", "ioredis",
    "mongodb", "cassandra-driver", "elasticsearch", "pg-pool",
    # Scraping, documentos y cloud
    "cheerio", "puppeteer", "playwright", "jsdom", "marked", "markdown-it",
    "sharp", "nodemailer", "stripe", "twilio", "firebase", "aws-sdk",
    # Build y testing
    "typescript", "tslib", "tsx", "ts-node", "esbuild", "webpack", "rollup",
    "vite", "babel", "eslint", "prettier", "jest", "vitest", "mocha", "chai",
    "sinon", "supertest", "nodemon", "concurrently", "husky", "lint-staged",
}

# Paquetes legítimos conocidos que quedan a distancia 1 de alguno popular.
PAQUETES_LEGITIMOS_EXTRA = {
    "core", "rest", "nest", "vike", "cuid", "less", "sass", "gulp", "grunt",
    "tape", "ava", "test", "list", "link", "lock", "path", "math", "time",
    "date", "data", "file", "find", "pipe", "port", "post", "pool", "tool",
    "text", "temp", "term", "tree", "trim", "type", "json5", "fetch", "sharp",
    "serve", "shell", "slack", "split", "stack", "start", "state", "store",
    "style", "super", "swift", "table", "token", "trace", "track", "trust",
    "valid", "value", "watch", "write",
}

# --- 3. Secretos hardcodeados ---

EXTENSIONES_IGNORADAS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip", ".tar",
    ".gz", ".tgz", ".wasm", ".bin", ".exe", ".dll", ".so", ".dylib",
    ".map",
}

ARCHIVOS_IGNORADOS_SECRETOS = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
}

# Patrones de alta confianza (estilo Gitleaks)
REGLAS_SECRETOS: list[tuple[str, str, re.Pattern]] = [
    ("secreto-aws-access-key", "alta", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    ("secreto-github-token", "alta", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("secreto-github-pat", "alta", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("secreto-openai-anthropic-stripe", "alta", re.compile(
        r"\b(?:sk-(?:proj-|ant-api\d+-|live-|test-)?[A-Za-z0-9_-]{16,}|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,})\b"
    )),
    ("secreto-slack-token", "alta", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("secreto-slack-webhook", "alta", re.compile(
        r"https://hooks\.slack\.com/services/T[A-Z0-9]{6,}/B[A-Z0-9]{6,}/[A-Za-z0-9]{16,}"
    )),
    ("secreto-discord-webhook", "alta", re.compile(
        r"https://discord(?:app)?\.com/api/webhooks/\d{15,}/[A-Za-z0-9_-]{30,}"
    )),
    ("secreto-google-api-key", "alta", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("secreto-clave-privada", "alta", re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"
    )),
    ("secreto-asignacion-credencial", "media", re.compile(
        r"""(?i)\b(?:api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token|client[_-]?secret|private[_-]?key|webhook[_-]?secret)\b\s*[:=]\s*["']([A-Za-z0-9+/=_-]{20,})["']"""
    )),
]

PLACEHOLDERS = re.compile(
    r"(?i)(your[_-]|example|placeholder|changeme|replace[_-]|insert[_-]|dummy|fake|xxxxxx|000000|12345678)"
)


def _damerau_levenshtein(a: str, b: str) -> int:
    """Distancia de edición incluyendo transposición de dos letras adyacentes."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 2:
        return 3
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            costo = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,      # borrado
                d[i][j - 1] + 1,      # inserción
                d[i - 1][j - 1] + costo,  # sustitución
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)  # transposición
    return d[la][lb]


def _buscar_linea(texto: str, aguja: str) -> int:
    for idx, linea in enumerate(texto.splitlines(), start=1):
        if aguja in linea:
            return idx
    return 1


def _archivos_package_json(codigo: Path) -> list[Path]:
    return [
        p for p in codigo.rglob("package.json")
        if "node_modules" not in p.parts
    ]


def detectar_scripts_instalacion(dir_servidor: Path) -> list[dict]:
    codigo = dir_servidor / "codigo"
    if not codigo.exists():
        return []
    base = dir_servidor.resolve()
    hallazgos = []

    for pkg_path in _archivos_package_json(codigo):
        try:
            texto = pkg_path.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(texto)
        except (OSError, json.JSONDecodeError):
            continue
        scripts = data.get("scripts")
        if not isinstance(scripts, dict):
            continue

        ruta = pkg_path.resolve().relative_to(base).as_posix()
        for hook in HOOKS_INSTALACION:
            comando = scripts.get(hook)
            if not isinstance(comando, str) or not comando.strip():
                continue
            es_peligroso = bool(PATRON_SCRIPT_ALTO_RIESGO.search(comando))
            linea = _buscar_linea(texto, f'"{hook}"')
            hallazgos.append(hallazgo(
                servidor=dir_servidor.name,
                categoria="script-instalacion",
                regla=f"script-{hook}-peligroso" if es_peligroso else f"script-{hook}",
                severidad="alta" if es_peligroso else "media",
                evidencia=f"{hook}: {comando}",
                ubicacion=f"{ruta}:{linea}",
            ))
    return hallazgos


def detectar_typosquat(dir_servidor: Path) -> list[dict]:
    codigo = dir_servidor / "codigo"
    if not codigo.exists():
        return []
    base = dir_servidor.resolve()
    conocidos = PAQUETES_POPULARES | PAQUETES_LEGITIMOS_EXTRA
    hallazgos = []

    for pkg_path in _archivos_package_json(codigo):
        try:
            texto = pkg_path.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(texto)
        except (OSError, json.JSONDecodeError):
            continue

        ruta = pkg_path.resolve().relative_to(base).as_posix()
        deps_vistas = set()

        for seccion in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            bloque = data.get(seccion)
            if not isinstance(bloque, dict):
                continue
            for dep in bloque:
                dep_norm = dep.strip().lower()
                if dep_norm in deps_vistas or dep_norm in conocidos:
                    continue
                if dep_norm.startswith("@types/"):
                    continue
                deps_vistas.add(dep_norm)

                # Comparar contra paquetes populares
                for pop in PAQUETES_POPULARES:
                    # Evitar ruido en nombres demasiado cortos (ej. ws/ms/pg)
                    if min(len(dep_norm), len(pop)) < 4:
                        continue
                    dist = _damerau_levenshtein(dep_norm, pop)
                    umbral = 2 if len(pop) >= 12 else 1
                    if 1 <= dist <= umbral:
                        linea = _buscar_linea(texto, f'"{dep}"')
                        hallazgos.append(hallazgo(
                            servidor=dir_servidor.name,
                            categoria="dependencia-typosquat",
                            regla="typosquat-distancia-edicion",
                            severidad="alta",
                            evidencia=f"'{dep}' es sospechosamente similar al paquete popular '{pop}' (distancia {dist})",
                            ubicacion=f"{ruta}:{linea}",
                        ))
                        break
    return hallazgos


def _es_probable_secreto_generico(valor: str) -> bool:
    """Filtra falsos positivos en la regla genérica de asignaciones."""
    if PLACEHOLDERS.search(valor):
        return False
    tiene_letras = any(c.isalpha() for c in valor)
    tiene_digitos = any(c.isdigit() for c in valor)
    # Exige mezcla de letras y números para no marcar frases o rutas
    return tiene_letras and tiene_digitos and len(set(valor)) >= 8


CLAVE_RECORTADA = re.compile(r"…|\.\.\.|<[^>]*>|\bREDACTED\b|\bEXAMPLE\b", re.IGNORECASE)


def _clave_recortada(resto_de_linea: str) -> bool:
    """Ejemplo de documentación ("-----BEGIN PRIVATE KEY-----\\n…\\n-----END...") y no una clave real."""
    return bool(CLAVE_RECORTADA.search(resto_de_linea[:200]))


def detectar_secretos(dir_servidor: Path) -> list[dict]:
    codigo = dir_servidor / "codigo"
    if not codigo.exists():
        return []
    base = dir_servidor.resolve()
    hallazgos = []

    for archivo in codigo.rglob("*"):
        if not archivo.is_file():
            continue
        if "node_modules" in archivo.parts or ".git" in archivo.parts:
            continue
        if archivo.name in ARCHIVOS_IGNORADOS_SECRETOS:
            continue
        if archivo.suffix.lower() in EXTENSIONES_IGNORADAS:
            continue
        # Saltar archivos enormes (> 2 MB) para no colgar regex
        try:
            if archivo.stat().st_size > 2_000_000:
                continue
            texto = archivo.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        ruta = archivo.resolve().relative_to(base).as_posix()
        for num_linea, linea in enumerate(texto.splitlines(), start=1):
            if len(linea) > 10_000:
                # En archivos minificados en una sola línea, igual buscamos secretos específicos
                # pero evitamos imprimir 10k chars en evidencia
                pass
            for regla_id, severidad, patron in REGLAS_SECRETOS:
                m = patron.search(linea)
                if not m:
                    continue
                if regla_id == "secreto-asignacion-credencial":
                    if not _es_probable_secreto_generico(m.group(1)):
                        continue
                if regla_id == "secreto-clave-privada" and _clave_recortada(linea[m.end():]):
                    continue

                inicio = max(0, m.start() - 25)
                fin = min(len(linea), m.end() + 25)
                recorte = linea[inicio:fin].strip()
                hallazgos.append(hallazgo(
                    servidor=dir_servidor.name,
                    categoria="secreto-hardcodeado",
                    regla=regla_id,
                    severidad=severidad,
                    evidencia=recorte,
                    ubicacion=f"{ruta}:{num_linea}",
                ))
                break  # un hallazgo de secreto por línea basta
    return hallazgos


def analizar_python(dir_servidor: Path) -> list[dict]:
    return (
        detectar_scripts_instalacion(dir_servidor)
        + detectar_typosquat(dir_servidor)
        + detectar_secretos(dir_servidor)
    )