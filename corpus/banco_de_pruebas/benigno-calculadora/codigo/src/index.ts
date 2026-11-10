import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

// BANCO DE PRUEBAS MCPScan: benigno-calculadora. Solo para evaluar la herramienta.

const server = new McpServer({ name: "benigno-calculadora", version: "1.0.0" });

server.tool(
  "sumar",
  "Suma dos números y devuelve el resultado.",
  { a: z.number(), b: z.number() },
  async ({ a, b }) => {
    return { content: [{ type: "text" as const, text: String(a + b) }] };
  },
);

server.tool(
  "multiplicar",
  "Multiplica dos números y devuelve el resultado.",
  { a: z.number(), b: z.number() },
  async ({ a, b }) => {
    return { content: [{ type: "text" as const, text: String(a * b) }] };
  },
);

await server.connect(new StdioServerTransport());
