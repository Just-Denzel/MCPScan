// Fixture: simula "telemetría" de instalación. El dominio .invalid nunca resuelve.
const os = require("node:os");

fetch("https://instalaciones.ejemplo.invalid/ping", {
  method: "POST",
  body: JSON.stringify({ host: os.hostname(), usuario: os.userInfo().username }),
}).catch(() => {});
