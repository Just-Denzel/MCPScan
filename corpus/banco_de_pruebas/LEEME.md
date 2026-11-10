# Banco de pruebas de MCPScan

18 servidores MCP escritos por el equipo para medir precisión y recall:
6 benignos (4 de ellos parecidos a los maliciosos, para medir falsos positivos) y 12 con un problema conocido.
Misma estructura que el corpus real: una carpeta por servidor con
`manifest.json`, `herramientas.json` y `codigo/`.

- `ground_truth.json` tiene la respuesta correcta de cada servidor (etiqueta,
  categorías esperadas, archivo y línea). **El pipeline no debe leerlo al analizar**;
  solo lo usa el módulo de evaluación.
- Todos son fixtures inertes: los destinos de red usan el dominio reservado
  `.invalid`, que nunca resuelve; las claves son de ejemplo; no hay comportamiento
  dañino real. Aun así, no los publiques como paquetes ni los instales con scripts
  (`npm install --ignore-scripts`).

Se regeneran con `python -m frente_c_pipeline.generar_banco corpus/banco_de_pruebas`.

| Servidor | Etiqueta | Qué prueba |
| --- | --- | --- |
| benigno-calculadora | benigno | Control limpio |
| benigno-notas | benigno | Uso seguro de archivos (falsos positivos) |
| benigno-ping-seguro | benigno | `execFile` sin shell: versión segura del de inyección |
| benigno-api-clima | benigno | Red y variable de entorno usadas de forma legítima |
| benigno-busqueda-proyecto | benigno | Descripción con "Importante" y "credenciales", sin ataque |
| benigno-codificar-base64 | benigno | Usa base64 sin ejecutar nada (falsos positivos de ofuscación) |
| poison-instruccion-oculta | malicioso | Tool poisoning evidente (`<IMPORTANT>`) |
| poison-unicode-invisible | malicioso | Texto oculto en Unicode invisible |
| poison-parafraseado | malicioso | Tool poisoning sin palabras clave |
| vuln-inyeccion-comandos | malicioso | Command injection vía parámetro |
| exfil-variables-entorno | malicioso | Envío de variables de entorno |
| lectura-archivos-sensibles | malicioso | Lee `~/.ssh` y `~/.aws` |
| postinstall-sospechoso | malicioso | Script `postinstall` que sale a la red |
| secretos-y-typosquat | malicioso | Secretos en código y dependencia `lodahs` |
| poison-parametro | malicioso | Instrucción oculta en la descripción de un parámetro |
| poison-otra-herramienta | malicioso | Manipula el uso de una herramienta de otro servidor |
| ofuscado-base64 | malicioso | Código en base64 ejecutado con `new Function` |
| exfil-minificado | malicioso | Exfiltración en código minificado dentro de `dist/` |
