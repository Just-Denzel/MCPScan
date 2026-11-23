# Corpus

- `banco_de_pruebas/`: 18 servidores propios, con respuestas conocidas (`ground_truth.json`): 6 benignos y 12 maliciosos. Es el conjunto de **desarrollo**. Es lo que se usa para medir precisión y recall. Está versionado en git. **No se edita a mano**: se edita `frente_c_pipeline/generar_banco.py` y se regenera con `python -m frente_c_pipeline.generar_banco corpus/banco_de_pruebas` (un test lo comprueba).
- `validacion/`: conjunto de **validación**, con 13 variantes que no se vieron al escribir las reglas. No está en el repositorio, para que siga siendo un conjunto ciego (ver `frente_c_pipeline/README.md`).
- `real/`: servidores públicos de npm. **No se sube a git.** Se descarga exactamente la misma muestra desde la lista guardada en `muestra_real.json`:

```bash
python frente_a_estatico/recolectar.py corpus/real --desde-muestra corpus/muestra_real.json
```
- `muestra_control.json`: 67 servidores del 9 de noviembre que no están en la muestra oficial. **No se usó para ajustar reglas**: sirve para comprobar que una mejora generaliza (`python frente_a_estatico/recolectar.py corpus/control --desde-muestra corpus/muestra_control.json`).
- `muestra_real.json`: la muestra oficial (paquete, versión e integridad de los 100 servidores), tomada del registry el 22 de noviembre de 2026. Está versionada; no contiene hallazgos, solo qué se analizó.

Formato de cada carpeta: ver [docs/formatos.md](../docs/formatos.md).

Los servidores del banco de pruebas son inertes (dominios `.invalid`, claves de ejemplo); no se publican como paquetes y se instalan sin scripts (`npm install --ignore-scripts`).
