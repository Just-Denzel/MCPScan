import { execSync } from "child_process";
server.registerTool("historial", { inputSchema: {} }, async (args) => {
  const cmd = "git log " + args.rama;
  return execSync(cmd).toString();               // DEBE: vía variable
});
const pid = Number(proc.pid);
execSync(`ps -p ${pid}`);                        // NO: fuera de una herramienta
