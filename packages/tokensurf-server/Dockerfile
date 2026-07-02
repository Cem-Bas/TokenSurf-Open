# syntax=docker/dockerfile:1
# Build context: repo root (set in docker-compose.yml so both packages are available).

FROM python:3.11-slim

# Install uv
RUN pip install --no-cache-dir uv==0.4.*

WORKDIR /workspace

# Copy workspace configuration and both packages.
# tokensurf-server depends on the local tokensurf library (workspace = true).
COPY pyproject.toml uv.lock* ./
COPY packages/tokensurf/ packages/tokensurf/
COPY packages/tokensurf-server/ packages/tokensurf-server/

# Sync server package without dev dependencies.
WORKDIR /workspace/packages/tokensurf-server
RUN uv sync --no-dev

EXPOSE 8000

# Run migrations then start uvicorn.
CMD ["sh", "-c", "uv run tokensurf-server migrate && uv run uvicorn tokensurf_server.app:app --host 0.0.0.0 --port 8000"]
