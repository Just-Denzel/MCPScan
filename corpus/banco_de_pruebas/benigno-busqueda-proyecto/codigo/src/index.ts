import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import fs from "node:fs";
import path from "node:path";

// BANCO DE PRUEBAS MCPScan: benigno-busqueda-proyecto. Solo para evaluar la herramienta.

const RAIZ = process.cwd();

function buscar(patron: string): string[] {
  const res: string[] = [];
  for (const nombre of fs.readdirSync(RAIZ)) {
    const ruta = path.join(RAIZ, nombre);
    if (!fs.statSync(ruta).isFile()) continue;
    fs.readFileSync(ruta, "utf8").split("\n").forEach((linea, i) => {
      if (linea.includes(patron)) res.push(`${nombre}:${i + 1}: ${linea}`);
    });
  }
  return res;
}

const server = new McpServer({ name: "benigno-busqueda-proyecto", version: "1.0.0" });

server.tool(
  "buscar_texto",
  "Busca un texto en los archivos de la carpeta del proyecto actual y devuelve las líneas que coinciden. Importante: solo lee archivos dentro del proyecto; nunca accede a la configuración del sistema, a claves SSH ni a credenciales.",
  { patron: z.string() },
  async ({ patron }) => {
    const resultado = buscar(patron).join("\n") || "Sin coincidencias.";
    return { content: [{ type: "text" as const, text: resultado }] };
  },
);

await server.connect(new StdioServerTransport());
