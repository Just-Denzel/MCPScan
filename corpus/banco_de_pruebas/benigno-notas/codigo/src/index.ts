import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import fs from "node:fs";
import path from "node:path";

// BANCO DE PRUEBAS MCPScan: benigno-notas. Solo para evaluar la herramienta.

const DIR = path.resolve("notas");
fs.mkdirSync(DIR, { recursive: true });

// Solo el nombre base: evita salir del directorio de notas.
function ruta(titulo: string): string {
  return path.join(DIR, path.basename(titulo) + ".txt");
}

const server = new McpServer({ name: "benigno-notas", version: "1.0.0" });

server.tool(
  "guardar_nota",
  "Guarda una nota de texto con el título indicado.",
  { titulo: z.string(), contenido: z.string() },
  async ({ titulo, contenido }) => {
    fs.writeFileSync(ruta(titulo), contenido);
    return { content: [{ type: "text" as const, text: "Nota guardada." }] };
  },
);

server.tool(
  "leer_nota",
  "Lee una nota guardada a partir de su título.",
  { titulo: z.string() },
  async ({ titulo }) => {
    const contenido = fs.readFileSync(ruta(titulo), "utf8");
    return { content: [{ type: "text" as const, text: contenido }] };
  },
);

await server.connect(new StdioServerTransport());
