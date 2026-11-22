server.tool("t", "d", { html: z.string() }, async ({ html }) => {
  const m = /<title>(.*?)<\/title>/i.exec(html);   // NO: expresión regular
  const re = /a/; re.exec(html);                     // NO
});
function buscar(x: string) { return /a/.exec(x); }
server.tool("u", "d", { q: z.string() }, async ({ q }) => { buscar(q); });   // NO
