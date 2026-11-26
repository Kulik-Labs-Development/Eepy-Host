#!/bin/sh
# eepy-sidecar entrypoint shim for the Backblaze b2-mcp image.
#
# b2-mcp's HTTP transport enforces a Host/Origin allowlist (hostOriginAllowed
# in src/http-fetch-handler.ts). With B2_ALLOWED_HOSTS unset, the default
# policy only accepts loopback Host headers - but the Eepy bridge dials the
# sidecar by its docker-network container IP, so every MCP handshake 403s
# with "Host/Origin not allowed". The container IP is assigned at spawn and
# is the one address the bridge uses, so allow it (plus loopback, for the
# docker healthcheck) before exec'ing the upstream entrypoint.
set -eu

IP="$(node -e 'const n=Object.values(require("node:os").networkInterfaces()).flat().find(i=>i&&!i.internal&&i.family==="IPv4");process.stdout.write(n?n.address:"")')"

export B2_ALLOWED_HOSTS="${B2_ALLOWED_HOSTS:+${B2_ALLOWED_HOSTS},}127.0.0.1,localhost${IP:+,$IP}"

exec node /app/dist/index.js "$@"
