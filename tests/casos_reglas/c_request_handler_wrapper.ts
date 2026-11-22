import { execSync } from "child_process";
function runCli(args: string): string {
  try {
    return execSync(`mc ${args}`, { encoding: "utf-8" }).trim();
  } catch (e) { return "error"; }
}
function fijo(): string { return execSync("mc wallet").toString(); }
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  switch (name) {
    case "info": { const out = runCli(`info ${args!.token}`); return out; }   // DEBE: wrapper
    case "wallet": { return fijo(); }                                       // NO
  }
});
