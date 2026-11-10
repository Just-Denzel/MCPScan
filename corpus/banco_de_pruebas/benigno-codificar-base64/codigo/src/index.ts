import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

// BANCO DE PRUEBAS MCPScan: benigno-codificar-base64. Solo para evaluar la herramienta.

const server = new McpServer({ name: "benigno-codificar-base64", version: "1.0.0" });

server.tool(
  "codificar_base64",
  "Codifica un texto en base64.",
  { texto: z.string() },
  async ({ texto }) => {
    return { content: [{ type: "text" as const, text: Buffer.from(texto, "utf8").toString("base64") }] };
  },
);

await server.connect(new StdioServerTransport());
