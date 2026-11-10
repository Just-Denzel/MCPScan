// Ejecuta un servidor MCP por stdio, lista sus herramientas, las llama con datos
// de prueba y busca señuelos (honeytokens) en las respuestas.
//
// 1. Llamada normal: si la respuesta ya trae un señuelo, el servidor lee archivos
//    sensibles por su cuenta  -> lectura-archivo-sensible.
// 2. Llamadas con payloads en cada parámetro de texto: si el señuelo aparece SOLO
//    con el payload, la vulnerabilidad queda confirmada:
//      payload de comando -> ejecucion-de-comando (command injection)
//      payload de ruta    -> lectura-archivo-sensible (path traversal)
//
// Uso: node cliente_mcp.mjs <dir_codigo_del_servidor>
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const codigo = path.resolve(process.argv[2]);
const nombre = path.basename(path.dirname(codigo));
const CANARIO = /HONEYTOKEN-[A-Z0-9-]+/g;
const MS = 15000;
// Directorio de trabajo temporal: el código del servidor se monta de solo lectura.
const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "mcp-"));
const LLAVE = path.join(os.homedir(), ".ssh", "id_rsa");

const PAYLOADS = [
  { tipo: "comando", valor: "127.0.0.1; cat ~/.ssh/id_rsa" },
  { tipo: "comando", valor: "x | cat ~/.ssh/id_rsa" },
  { tipo: "ruta", valor: path.relative(cwd, LLAVE) },  // ../../home/.../.ssh/id_rsa
];
const CATEGORIA = { comando: "ejecucion-de-comando", ruta: "lectura-archivo-sensible" };
const REGLA = { comando: "inyeccion-confirmada", ruta: "traversal-confirmado" };

const transport = new StdioClientTransport({
  command: "node",
  args: ["--experimental-strip-types", "--no-warnings", path.join(codigo, "src", "index.ts")],
  cwd,
  stderr: "pipe",
});
const cliente = new Client({ name: "mcpscan-sandbox", version: "0.2.0" });
const informe = { servidor: nombre, herramientas: [], hallazgos: [], error: null };
const stderrBuf = [];
transport.stderr?.on("data", (d) => stderrBuf.push(String(d)));

const conTiempo = (p, msg) =>
  Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(msg)), MS))]);

const ejemplo = (schema) => {
  const args = {};
  for (const [k, v] of Object.entries(schema?.properties ?? {})) {
    if (!(schema.required ?? []).includes(k)) continue;
    args[k] = v.type === "number" ? 1 : "prueba";
  }
  return args;
};

async function llamar(herramienta, args) {
  try {
    const r = await conTiempo(cliente.callTool({ name: herramienta, arguments: args }), "timeout en herramienta");
    return (r.content ?? []).map((c) => c.text ?? "").join("\n");
  } catch (e) {
    return `ERROR: ${e.message ?? e}`;
  }
}

const canarios = (texto) => new Set(texto.match(CANARIO) ?? []);
const ya = new Set();
function hallazgo(categoria, regla, herramienta, evidencia) {
  const clave = `${categoria}|${herramienta}`;
  if (ya.has(clave)) return;
  ya.add(clave);
  informe.hallazgos.push({
    servidor: nombre, categoria, regla, severidad: "alta",
    evidencia, ubicacion: `dinamico:${herramienta}`, analizador: "sandbox",
  });
}

try {
  await conTiempo(cliente.connect(transport), "timeout al conectar");
  const { tools } = await cliente.listTools();
  for (const t of tools) {
    const base = ejemplo(t.inputSchema);
    const entrada = { nombre: t.name, descripcion: t.description, args: base, payloads: [] };
    const respuesta = await llamar(t.name, base);
    entrada.respuesta = respuesta.slice(0, 500);
    const enBase = canarios(respuesta);
    if (enBase.size) {
      hallazgo("lectura-archivo-sensible", "honeytoken-en-respuesta", t.name,
        `la respuesta normal de ${t.name} contiene señuelos: ${[...enBase].join(", ")}`);
    }
    const deTexto = Object.entries(t.inputSchema?.properties ?? {})
      .filter(([, v]) => v.type === "string").map(([k]) => k);
    for (const param of deTexto) {
      for (const p of PAYLOADS) {
        const resp = await llamar(t.name, { ...base, [param]: p.valor });
        const nuevos = [...canarios(resp)].filter((c) => !enBase.has(c));
        entrada.payloads.push({ param, tipo: p.tipo, filtro: nuevos.length > 0 });
        if (nuevos.length) {
          hallazgo(CATEGORIA[p.tipo], REGLA[p.tipo], t.name,
            `con '${param}' = ${JSON.stringify(p.valor)} la respuesta filtra ${nuevos.join(", ")}`);
        }
      }
    }
    informe.herramientas.push(entrada);
  }
} catch (e) {
  informe.error = String(e.message ?? e);
} finally {
  await cliente.close().catch(() => {});
}
informe.stderr = stderrBuf.join("").slice(0, 500);
console.log(JSON.stringify(informe, null, 2));
process.exit(0);
