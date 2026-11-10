import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

// BANCO DE PRUEBAS MCPScan: secretos-y-typosquat. Solo para evaluar la herramienta.

// Claves de ejemplo: la de AWS es la que aparece en su documentación pública.
const CLAVE_API = "sk-test-FAKE0123456789abcdef0123456789abcdef";
const AWS_ID = "AKIAIOSFODNN7EXAMPLE";
const AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY";

function autenticar(): Record<string, string> {
  return { Authorization: `Bearer ${CLAVE_API}`, "X-Aws-Id": AWS_ID, "X-Aws-Secret": AWS_SECRET };
}

const server = new McpServer({ name: "secretos-y-typosquat", version: "1.0.0" });

server.tool(
  "buscar_definicion",
  "Busca la definición de un término.",
  { termino: z.string() },
  async ({ termino }) => {
    void autenticar();
    return { content: [{ type: "text" as const, text: `Definición de ${termino}: (texto de ejemplo)` }] };
  },
);

await server.connect(new StdioServerTransport());
