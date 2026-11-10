import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

// BANCO DE PRUEBAS MCPScan: benigno-api-clima. Solo para evaluar la herramienta.

// Dominio de la API declarado en la documentación del servidor.
const API = "https://api.clima.ejemplo.invalid/v1/actual";

async function consultar(ciudad: string): Promise<string> {
  try {
    const r = await fetch(`${API}?ciudad=${encodeURIComponent(ciudad)}`, {
      headers: { Authorization: `Bearer ${process.env.CLIMA_API_KEY ?? ""}` },
    });
    return await r.text();
  } catch {
    return `Clima en ${ciudad}: 18 °C, despejado (dato de ejemplo).`;
  }
}

const server = new McpServer({ name: "benigno-api-clima", version: "1.0.0" });

server.tool(
  "obtener_clima",
  "Devuelve el clima actual de una ciudad usando la API de clima configurada en CLIMA_API_KEY.",
  { ciudad: z.string() },
  async ({ ciudad }) => {
    const resultado = await consultar(ciudad);
    return { content: [{ type: "text" as const, text: resultado }] };
  },
);

await server.connect(new StdioServerTransport());
