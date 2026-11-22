"""La muestra de servidores reales se puede guardar y leer (sin red)."""
import json

from frente_a_estatico.recolectar import carpeta_de, exportar_muestra


def test_exportar_muestra(tmp_path):
    corpus = tmp_path / "real"
    for paquete, version in (("@org/servidor-uno", "1.0.0"), ("servidor-dos", "2.1.0")):
        d = carpeta_de(corpus, paquete)
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({
            "fuente": "npm", "paquete": paquete, "version": version, "integridad": "sha512-x",
            "fecha_descarga": "2026-11-22"}), encoding="utf-8")
    archivo = tmp_path / "muestra.json"
    exportar_muestra(corpus, archivo)
    m = json.loads(archivo.read_text(encoding="utf-8"))
    assert m["fecha_descarga"] == "2026-11-22"
    assert [(s["paquete"], s["version"]) for s in m["servidores"]] == [
        ("@org/servidor-uno", "1.0.0"), ("servidor-dos", "2.1.0")]
