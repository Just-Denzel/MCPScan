"""El formato de hallazgo y las categorías (comun/formatos.py)."""
import json
from pathlib import Path

import pytest

from comun.formatos import CATEGORIAS, hallazgo, validar

RAIZ = Path(__file__).resolve().parent.parent


def test_hallazgo_valido():
    h = hallazgo("srv", "ejecucion-de-comando", "regla-x", "alta", "exec(x)", "codigo/a.ts:1")
    assert validar(h) == []


@pytest.mark.parametrize("cambio, error", [
    ({"categoria": "ejecucion-comando"}, "categoría desconocida"),   # error de tipeo típico
    ({"severidad": "critica"}, "severidad inválida"),
    ({"ubicacion": ""}, "falta el campo 'ubicacion'"),
])
def test_hallazgo_invalido(cambio, error):
    h = {"servidor": "s", "categoria": "ejecucion-de-comando", "regla": "r",
         "severidad": "alta", "evidencia": "e", "ubicacion": "u"} | cambio
    assert any(error in p for p in validar(h))
    with pytest.raises(ValueError):
        hallazgo(**h)


def test_ground_truth_usa_categorias_del_contrato():
    gt = json.loads((RAIZ / "corpus/banco_de_pruebas/ground_truth.json").read_text(encoding="utf-8"))
    usadas = {h["categoria"] for s in gt["servidores"] for h in s["hallazgos_esperados"]}
    assert usadas <= set(CATEGORIAS)
