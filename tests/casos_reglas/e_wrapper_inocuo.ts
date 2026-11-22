import { execSync } from "child_process";
function formatear(x: string): string { return x.toUpperCase(); }
function ejecutarFijo(x: string): string { return execSync("ls").toString() + x; }
server.tool("fmt", "desc", { t: z.string() }, async ({ t }) => {
  formatear(t);       // NO: la función no ejecuta nada
  ejecutarFijo(t);    // NO: ejecuta un comando fijo, el parámetro no llega a la shell
});
