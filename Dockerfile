# One Linux amd64 image: Node builds the Vue app, FastAPI serves it and /api.
# Builds are performed by Cloud Build in the deployment stage; this file is not
# evidence that an image has been built locally.

FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/vite.config.js ./
COPY frontend/src ./src
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    FRONTEND_DIR=/app/dist \
    PATH="/app/.venv/bin:$PATH"
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home app \
    && pip install --no-cache-dir uv==0.13.4

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/alembic.ini ./
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY --from=frontend-build /build/dist ./dist
COPY --chown=10001:10001 scripts/container-entrypoint.sh ./scripts/container-entrypoint.sh
RUN chmod 0755 ./scripts/container-entrypoint.sh

USER 10001:10001
EXPOSE 8080
# Migrations, seed, and session cleanup run as explicit commands on this same
# image (see docs/deployment/t2-runbook.md), never at API startup.
ENTRYPOINT ["/app/scripts/container-entrypoint.sh"]
