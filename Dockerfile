# Perry relay server + PWA in one image. Run as a single process (WebSocket state is in-memory).
FROM node:24-slim AS web
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra server
COPY --from=web /web/dist ./web/dist
ENV HOST=0.0.0.0 PORT=8787 DB_PATH=/data/perry.db
VOLUME /data
EXPOSE 8787
CMD ["uv", "run", "--no-sync", "perry-server"]
