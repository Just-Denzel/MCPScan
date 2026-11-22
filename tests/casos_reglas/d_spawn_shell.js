const cp = require("child_process");
server.tool("correr", "desc", { script: z.string() }, async ({ script }) => {
  cp.spawn("bash", ["-c", script]);                // DEBE
  cp.spawn("node", [script], { shell: false });    // NO: sin shell
  cp.execFile("git", ["log", script]);             // NO: sin shell
});
