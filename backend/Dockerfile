# Build from the repo root: docker build -f backend/Dockerfile .
FROM node:22-slim AS frontend
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json frontend/
RUN pnpm install --frozen-lockfile
COPY frontend frontend
RUN pnpm --filter frontend build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend ./
COPY --from=frontend /repo/frontend/dist /app/frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist \
    STORAGE_DIR=/data/files \
    PATH="/app/backend/.venv/bin:$PATH"
RUN mkdir -p /data/files
EXPOSE 8000
# Railway terminates TLS at its proxy: trust X-Forwarded-* (request.client is the login rate-limit
# key). The container is only reachable through that proxy. the scheduler overrides it with a dashboard start command.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
