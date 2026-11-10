import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

// BANCO DE PRUEBAS MCPScan: postinstall-sospechoso. Solo para evaluar la herramienta.

const server = new McpServer({ name: "postinstall-sospechoso", version: "1.0.0" });

server.tool(
  "contar_palabras",
  "Cuenta las palabras de un texto.",
  { texto: z.string() },
  async ({ texto }) => {
    return { content: [{ type: "text" as const, text: String(texto.split(/\s+/).filter(Boolean).length) }] };
  },
);

await server.connect(new StdioServerTransport());
