import pytest


@pytest.fixture(autouse=True)
def _sin_archivo_env(monkeypatch):
    """Los tests nunca leen el .env local: así no usan una clave real ni hacen llamadas pagadas."""
    from frente_b_descripciones import clasificador_llm
    monkeypatch.setattr(clasificador_llm, "cargar_env", lambda *a, **k: None)
