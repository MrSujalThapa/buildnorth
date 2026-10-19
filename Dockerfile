FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
COPY apps/api/src ./apps/api/src
COPY supabase/migrations ./supabase/migrations
COPY scripts/db_migrate.py ./scripts/db_migrate.py

RUN uv sync --frozen --no-dev

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'))"

# One process. MCP rate limits and goal write locks are process-local.
CMD ["sh", "-c", "uv run python scripts/db_migrate.py && exec uv run python -m personal_markets --host 0.0.0.0 --port ${PORT:-8000}"]
