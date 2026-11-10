// Ejecuta un servidor MCP por stdio, lista sus herramientas, las llama con datos
// de prueba y busca señuelos (honeytokens) en las respuestas.
// Uso: node cliente_mcp.mjs <dir_codigo_del_servidor> [dir_herramientas.json]
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const codigo = path.resolve(process.argv[2]);
const nombre = path.basename(path.dirname(codigo));
const CANARIO = /HONEYTOKEN-[A-Z0-9-]+/g;

const transport = new StdioClientTransport({
  command: "node",
  args: ["--experimental-strip-types", "--no-warnings", path.join(codigo, "src", "index.ts")],
  // Directorio de trabajo temporal: el código del servidor se monta de solo lectura.
  cwd: fs.mkdtempSync(path.join(os.tmpdir(), "mcp-")),
  stderr: "pipe",
});
const cliente = new Client({ name: "mcpscan-sandbox", version: "0.1.0" });
const informe = { servidor: nombre, herramientas: [], hallazgos: [], error: null };
const stderrBuf = [];
transport.stderr?.on("data", (d) => stderrBuf.push(String(d)));

const ejemplo = (schema) => {
  const args = {};
  for (const [k, v] of Object.entries(schema?.properties ?? {})) {
    if (!(schema.required ?? []).includes(k)) continue;
    args[k] = v.type === "number" ? 1 : "prueba";
  }
  return args;
};

try {
  await Promise.race([
    cliente.connect(transport),
    new Promise((_, rej) => setTimeout(() => rej(new Error("timeout al conectar")), 15000)),
  ]);
  const { tools } = await cliente.listTools();
  for (const t of tools) {
    const entrada = { nombre: t.name, descripcion: t.description, args: ejemplo(t.inputSchema) };
    try {
      const r = await Promise.race([
        cliente.callTool({ name: t.name, arguments: entrada.args }),
        new Promise((_, rej) => setTimeout(() => rej(new Error("timeout en herramienta")), 15000)),
      ]);
      const texto = (r.content ?? []).map((c) => c.text ?? "").join("\n");
      entrada.respuesta = texto.slice(0, 500);
      const canarios = [...new Set(texto.match(CANARIO) ?? [])];
      if (canarios.length) {
        informe.hallazgos.push({
          servidor: nombre,
          categoria: "lectura-archivo-sensible",
          regla: "honeytoken-en-respuesta",
          severidad: "alta",
          evidencia: `la respuesta de ${t.name} contiene señuelos: ${canarios.join(", ")}`,
          ubicacion: `dinamico:${t.name}`,
          analizador: "sandbox",
        });
      }
    } catch (e) {
      entrada.error = String(e.message ?? e);
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
