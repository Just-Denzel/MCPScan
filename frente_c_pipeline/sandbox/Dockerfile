# Imagen de ejecución aislada para los servidores MCP del banco de pruebas.
# Las dependencias se instalan al construir (con red); al ejecutar se corta la red.
FROM node:22-slim

# Todo vive bajo /sandbox: los servidores se montan en /sandbox/servidores/<nombre>/codigo
# y así encuentran las dependencias en /sandbox/node_modules (npm no instala bien en "/").
WORKDIR /sandbox
# Mismas versiones con las que se probó el banco de pruebas.
RUN npm init -y >/dev/null \
 && npm install --ignore-scripts --no-audit --no-fund @modelcontextprotocol/sdk@1.32.2 zod@4.6.7 \
 && npm cache clean --force

RUN useradd -m -u 10001 sandbox
# Señuelos: archivos y claves falsas que un servidor malicioso podría intentar leer.
RUN mkdir -p /home/sandbox/.ssh /home/sandbox/.aws \
 && echo "-----BEGIN FAKE KEY----- HONEYTOKEN-SSH-0001 -----END FAKE KEY-----" > /home/sandbox/.ssh/id_rsa \
 && printf "[default]\naws_access_key_id=HONEYTOKEN-AWS-0002\naws_secret_access_key=HONEYTOKEN-AWS-0003\n" > /home/sandbox/.aws/credentials \
 && chown -R sandbox:sandbox /home/sandbox && chmod 600 /home/sandbox/.ssh/id_rsa /home/sandbox/.aws/credentials

COPY cliente_mcp.mjs /sandbox/cliente_mcp.mjs
USER sandbox
ENV HOME=/home/sandbox AWS_SECRET_ACCESS_KEY=HONEYTOKEN-ENV-0004 API_TOKEN=HONEYTOKEN-ENV-0005
ENTRYPOINT ["node", "/sandbox/cliente_mcp.mjs"]
