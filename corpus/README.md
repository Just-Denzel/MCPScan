# Corpus

- `banco_de_pruebas/`: 13 servidores escritos por el equipo, con respuestas conocidas (`ground_truth.json`): 5 benignos y 8 maliciosos. Es lo que se usa para medir precisión y recall. Está versionado en git. **No se edita a mano**: se edita `frente_c_pipeline/generar_banco.py` y se regenera con `python -m frente_c_pipeline.generar_banco corpus/banco_de_pruebas` (un test lo comprueba).
- `real/`: servidores públicos de npm. **No se sube a git.** Se descarga con:

```bash
python frente_a_estatico/recolectar.py corpus/real --n 100
```

Formato de cada carpeta: ver [docs/formatos.md](../docs/formatos.md).

Los servidores del banco de pruebas son inertes (dominios `.invalid`, claves de ejemplo), pero no se publican como paquetes ni se instalan con scripts (`npm install --ignore-scripts`).
