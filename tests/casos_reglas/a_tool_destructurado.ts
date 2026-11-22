import { exec } from "node:child_process";
server.tool("ping", "desc", { host: z.string() }, async ({ host }) => {
  exec(`ping -c 1 ${host}`, () => {});           // DEBE: dato del modelo a shell
  exec("ls -la", () => {});                        // NO: fijo
  return { content: [] };
});
