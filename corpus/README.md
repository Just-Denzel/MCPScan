# Corpus

- `banco_de_pruebas/`: 18 servidores escritos por el equipo, con respuestas conocidas (`ground_truth.json`): 6 benignos y 12 maliciosos. Es el conjunto de **desarrollo**. Es lo que se usa para medir precisión y recall. Está versionado en git. **No se edita a mano**: se edita `frente_c_pipeline/generar_banco.py` y se regenera con `python -m frente_c_pipeline.generar_banco corpus/banco_de_pruebas` (un test lo comprueba).
- `validacion/`: conjunto de **validación privado**, con variantes que el resto del equipo no ve. **No se sube a git**; lo tiene solo el frente C y se usa al final (ver `frente_c_pipeline/README.md`).
- `real/`: servidores públicos de npm. **No se sube a git.** Se descarga, exactamente igual para todos, desde la lista guardada en `muestra_real.json`:

```bash
python frente_a_estatico/recolectar.py corpus/real --desde-muestra corpus/muestra_real.json
```
- `muestra_real.json`: la muestra oficial (paquete, versión e integridad de los 100 servidores), tomada del registry el 22 de noviembre de 2026. **Sí se sube a git.** No contiene hallazgos, solo qué se analizó.

Formato de cada carpeta: ver [docs/formatos.md](../docs/formatos.md).

Los servidores del banco de pruebas son inertes (dominios `.invalid`, claves de ejemplo), pero no se publican como paquetes ni se instalan con scripts (`npm install --ignore-scripts`).
