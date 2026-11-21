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
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend ./
COPY --from=frontend /repo/frontend/dist /app/frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist \
    PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
