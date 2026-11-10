#!/usr/bin/env bash
# Local demo: build the PWA, start the server, expose it over HTTPS with a Cloudflare quick tunnel.
set -euo pipefail
cd "$(dirname "$0")/.."
(cd web && pnpm install --frozen-lockfile && pnpm build)
uv sync --all-extras
uv run perry-server &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
sleep 2
echo "Starting HTTPS tunnel (the URL appears below as https://….trycloudflare.com)"
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8787
