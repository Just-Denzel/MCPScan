# Especificación de categorías

Qué cuenta como cada problema, qué no cuenta y en qué formas puede aparecer. **Las reglas y heurísticas se escriben contra esta especificación, no contra los casos del banco de pruebas.**

Por qué importa: el banco de desarrollo (`corpus/banco_de_pruebas`) tiene uno o dos ejemplos por categoría. Una regla hecha a la medida de ese ejemplo puede sacar 100 % ahí y fallar con cualquier variante. Al final del proyecto, los analizadores se evalúan también contra un **conjunto de validación** con variantes que ustedes no han visto, todas tomadas de las familias descritas abajo. La diferencia entre ambos resultados es la que muestra si una regla generaliza o solo memorizó el ejemplo.

Para cada categoría, piensen: ¿mi regla detecta *todas* las variantes listadas? ¿Marca alguno de los casos de "No cuenta"?

## Consideraciones generales

- El código puede estar en TypeScript o en **JavaScript compilado o minificado**, en carpetas como `dist/`, `lib/` o `build/`, con nombres de variables de una letra y todo en una línea. Hay que revisar todos los archivos del paquete, no solo `src/`.
- Un mismo dato puede llegar a la función peligrosa directamente, en una plantilla de texto, concatenado o pasando por una variable intermedia.
- Las APIs de Node se pueden importar de varias formas: `import x from "node:child_process"`, `"child_process"`, `require(...)`, importando solo la función o el módulo completo.
- El código peligroso puede correr al llamar a una herramienta, **al arrancar el servidor** o **al instalar el paquete**.

---

## Frente A: código

### `ejecucion-de-comando`
Un dato que controla el modelo (un parámetro de una herramienta) llega a un comando que interpreta una shell.

- **Variantes:** `exec`, `execSync`; `spawn` o `spawnSync` con `shell: true`; shells explícitas (`sh -c`, `bash -c`, `cmd /c`). El comando puede armarse con plantilla, con concatenación (`+`) o en una variable antes de ejecutarse.
- **No cuenta:** `execFile` o `spawn` con una **lista de argumentos y sin shell** (también `bash -c script -- dato`, donde el dato va como argumento y no como código); comandos fijos que no incluyen datos del modelo; el método `exec` de una expresión regular.
- **Severidad:** alta solo si se comprueba en el código que el dato viene de los argumentos de una herramienta MCP; media si el comando es dinámico pero no se sabe de dónde viene el dato.

### `exfiltracion-red`
Envía datos del usuario o del sistema a un destino externo que no tiene relación con lo que la herramienta dice hacer.

- **Datos típicos:** `process.env` completo, `os.hostname()`, `os.userInfo()`, la ruta de trabajo, contenido de archivos.
- **Variantes:** `fetch`, `http.request`, `https.request`, librerías como `axios`, `got` o `node-fetch`, sockets. También en código que corre al arrancar o al instalar, o en código minificado.
- **No cuenta:** llamar a la API que la herramienta declara usar, aunque mande un token propio de esa API leído desde una variable de entorno.

### `lectura-archivo-sensible`
Lee archivos con credenciales o secretos del usuario, sin que la función lo justifique.

- **Archivos típicos:** `~/.ssh/*`, `~/.aws/credentials`, `~/.npmrc`, `~/.netrc`, `~/.env`, `~/.config/*` (gcloud, kube, gh), perfiles y contraseñas del navegador.
- **Variantes:** rutas armadas con `os.homedir()`, `path.join`, concatenación de texto o `~`; lectura con `fs.readFileSync`, `fs.promises.readFile`, `readFile` importado de `node:fs/promises`, streams.
- **No cuenta:** archivos del propio proyecto (por ejemplo `config.json`, o el `.env` con la configuración del servidor o del proyecto en que trabaja); lecturas limitadas a una carpeta propia del servidor; textos que solo mencionan una ruta sensible sin leerla (documentación, descripciones, mensajes).

### `secreto-hardcodeado`
Claves o credenciales escritas en cualquier archivo del paquete.

- **Variantes:** claves de nube (AWS `AKIA...`), tokens de plataformas (GitHub `ghp_...`, Slack, claves `sk-...` de APIs de IA), URLs de webhooks con el secreto incluido, claves privadas. Pueden estar en constantes, objetos de configuración o encabezados.
- **Recomendado:** usar gitleaks en vez de escribir patrones a mano.

### `dependencia-typosquat`
Una dependencia con un nombre casi igual al de un paquete popular.

- **Variantes:** una letra cambiada, duplicada, faltante o dos letras transpuestas respecto de un paquete muy descargado (`lodash`, `axios`, `express`, `react`…).
- **No cuenta:** paquetes legítimos con nombres parecidos entre sí; hay que compararlos contra una lista de paquetes populares, no solo por distancia de texto.

### `script-instalacion`
El `package.json` define scripts que corren solos al instalar: `preinstall`, `install` o `postinstall`.

- **Más grave si:** descarga un script de internet y lo ejecuta en una shell, sale a la red o lee datos del sistema.
- **Ojo:** la presencia del script ya es la categoría. La severidad sube según lo que hace.

### `codigo-ofuscado`
Texto codificado que se decodifica y **se ejecuta** como código.

- **Codificaciones:** base64, hexadecimal, listas de códigos de caracteres (`String.fromCharCode`), texto invertido o partido en trozos.
- **Formas de ejecutarlo:** `eval`, `new Function(...)`, `vm.runInThisContext` y similares, `import()` o `require` dinámicos.
- **No cuenta:** codificar o decodificar datos sin ejecutarlos (por ejemplo, una herramienta que convierte texto a base64).

---

## Frente B: descripciones de herramientas

Las descripciones están en `herramientas.json`: la de cada herramienta en `descripcion`, y la de **cada parámetro** en `esquema.properties.<parámetro>.description`. El modelo lee ambas.

### `tool-poisoning-instruccion`
La descripción le da instrucciones al modelo que el usuario no vería ni esperaría.

- **Señales:** órdenes al asistente ("antes de…", "debes…"); pedir que lea archivos o credenciales, o que los mande en un parámetro; pedir que no se informe al usuario; **manipular cómo se usan otras herramientas**, incluso de otros servidores (*tool shadowing*).
- **Dónde se esconde:** en la descripción de la herramienta o de un parámetro; entre etiquetas tipo `<IMPORTANT>` o comentarios HTML; **después de muchas líneas o espacios en blanco**, para que no se vea en una interfaz.
- **No cuenta:** advertencias legítimas dirigidas al usuario, aunque usen palabras como "Importante", "credenciales" o "claves SSH" (por ejemplo, "Importante: nunca lee credenciales").

### `tool-poisoning-unicode`
La descripción contiene caracteres invisibles.

- **Variantes:** caracteres *tag* (U+E0000 a U+E007F), que codifican texto que no se ve; caracteres de ancho cero (U+200B, U+200C, U+200D, U+2060, U+FEFF), por ejemplo **intercalados entre letras** para que una búsqueda por palabras no encuentre la instrucción; controles de dirección del texto (U+202A a U+202E, U+2066 a U+2069).
- **Nota:** si el texto escondido es además una instrucción, el caso cuenta también como `tool-poisoning-instruccion`.

### `tool-poisoning-parafraseado`
Una instrucción maliciosa redactada para no parecerlo.

- **Variantes:** tono de recomendación o de "paso de rutina" en vez de orden; sin palabras clave típicas (*ignore*, *important*, *secret*); **en otro idioma** (inglés u otros).
- Es la categoría donde se espera que el clasificador LLM le gane a las heurísticas.
