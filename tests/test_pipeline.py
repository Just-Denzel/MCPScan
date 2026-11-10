"""El pipeline y el evaluador funcionan juntos sobre el banco de pruebas."""
import shutil
from pathlib import Path

import pytest

from frente_c_pipeline.evaluar import evaluar
from frente_c_pipeline.pipeline import correr

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "corpus/banco_de_pruebas"


class _Falla:
    @staticmethod
    def analizar(_):
        raise RuntimeError("explota")


def test_un_analizador_que_falla_no_detiene_la_corrida(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "analizador_que_falla", _Falla)
    hall, errores = correr(BANCO, ["frente_b_descripciones.analizador", "analizador_que_falla"])
    assert len(errores) == 13                      # uno por servidor
    assert any(h["servidor"] == "poison-instruccion-oculta" for h in hall)


def test_evaluar_cuenta_bien():
    gt = {"servidores": [
        {"servidor": "a", "etiqueta": "malicioso", "hallazgos_esperados": [{"categoria": "ejecucion-de-comando"}]},
        {"servidor": "b", "etiqueta": "benigno", "hallazgos_esperados": []},
    ]}
    hall = [
        {"servidor": "a", "categoria": "ejecucion-de-comando", "analizador": "x"},
        {"servidor": "b", "categoria": "exfiltracion-red", "analizador": "x"},
    ]
    r = evaluar(gt, hall)
    assert (r["global"]["tp"], r["global"]["fp"], r["global"]["fn"]) == (1, 1, 0)
    assert r["servidores"]["benignos_marcados"] == 1


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="Semgrep no instalado")
def test_pipeline_completo_sobre_el_banco():
    hall, errores = correr(BANCO, ["frente_a_estatico.analizador", "frente_b_descripciones.analizador"])
    assert errores == []
    pares = {(h["servidor"], h["categoria"]) for h in hall}
    assert ("vuln-inyeccion-comandos", "ejecucion-de-comando") in pares
    # Ningún benigno debe marcarse. Si este test falla, una regla nueva da falsos positivos.
    assert not [h for h in hall if h["servidor"].startswith("benigno-")]
