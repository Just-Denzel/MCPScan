"""Contrato entre los tres frentes: categorías, severidades y formato de hallazgo.

Es la única fuente de verdad. Si se agrega una categoría, se agrega aquí, en el
ground truth (frente_c_pipeline/generar_banco.py) y en docs/formatos.md.
"""

# categoría -> (frente que la detecta, descripción corta)
CATEGORIAS = {
    "ejecucion-de-comando": ("A", "Dato del modelo llega a un comando de shell"),
    "exfiltracion-red": ("A", "Envía datos a un dominio externo no declarado"),
    "lectura-archivo-sensible": ("A", "Lee ~/.ssh, ~/.aws, .env u otros archivos sensibles"),
    "secreto-hardcodeado": ("A", "Claves o credenciales en el código"),
    "dependencia-typosquat": ("A", "Dependencia con nombre parecido a una popular"),
    "script-instalacion": ("A", "preinstall, install o postinstall en package.json"),
    "tool-poisoning-instruccion": ("B", "Instrucción evidente al modelo en una descripción"),
    "tool-poisoning-unicode": ("B", "Texto oculto en caracteres Unicode invisibles"),
    "tool-poisoning-parafraseado": ("B", "Instrucción reformulada, sin palabras clave típicas"),
}

SEVERIDADES = ("alta", "media", "baja")
PESO_SEVERIDAD = {"alta": 3, "media": 2, "baja": 1}

# Campos que escribe cada analizador. El pipeline agrega "analizador".
CAMPOS = ("servidor", "categoria", "regla", "severidad", "evidencia", "ubicacion")
MAX_EVIDENCIA = 300


def validar(h: dict) -> list[str]:
    """Devuelve la lista de problemas del hallazgo (vacía si es válido)."""
    problemas = [f"falta el campo '{c}'" for c in CAMPOS if not h.get(c)]
    if h.get("categoria") and h["categoria"] not in CATEGORIAS:
        problemas.append(f"categoría desconocida '{h['categoria']}' (ver comun/formatos.py)")
    if h.get("severidad") and h["severidad"] not in SEVERIDADES:
        problemas.append(f"severidad inválida '{h['severidad']}' (alta, media o baja)")
    return problemas


def hallazgo(servidor: str, categoria: str, regla: str, severidad: str,
             evidencia: str, ubicacion: str) -> dict:
    """Construye un hallazgo válido o lanza ValueError. Usarlo en vez de armar el dict a mano."""
    h = {
        "servidor": servidor,
        "categoria": categoria,
        "regla": regla,
        "severidad": severidad,
        "evidencia": " ".join(str(evidencia).split())[:MAX_EVIDENCIA],
        "ubicacion": ubicacion,
    }
    problemas = validar(h)
    if problemas:
        raise ValueError(f"hallazgo inválido: {'; '.join(problemas)}")
    return h
