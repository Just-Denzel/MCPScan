import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { execFile } from "node:child_process";

// BANCO DE PRUEBAS MCPScan: benigno-ping-seguro. Solo para evaluar la herramienta.

const server = new McpServer({ name: "benigno-ping-seguro", version: "1.0.0" });

server.tool(
  "hacer_ping",
  "Comprueba si un equipo responde a un ping.",
  { host: z.string() },
  async ({ host }) => {
    const salida = await new Promise<string>((resolve) => {
      // execFile con lista de argumentos: no pasa por una shell, no hay inyección.
      execFile("ping", ["-c", "1", host], (_err, stdout, stderr) => resolve(stdout || stderr));
    });
    return { content: [{ type: "text" as const, text: salida }] };
  },
);

await server.connect(new StdioServerTransport());
