# Repovil

AI open-source repository momentum tracker. The backend and workers share one Python
package while the web UI is a separate Next.js application.

## Local setup

Requirements: Python 3.12+, uv, Node.js 20.9+, npm, and Docker Compose.

```bash
cp .env.example .env
uv sync
npm --prefix frontend ci
docker compose up -d --wait postgres
```

Run the development entry points in separate terminals:

```bash
uv run uvicorn repovil.api:app --reload
npm --prefix frontend run dev
```

The worker entry point is intentionally a no-op until the collection phases are
implemented:

```bash
uv run repovil-worker
```

Validate the category/topic discovery configuration without changing data:

```bash
uv run repovil-categories-check
```

## Quality checks

```bash
uv run pytest
uv run ruff check .
uv run mypy
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

With PostgreSQL running, include the connection smoke test:

```bash
TEST_DATABASE_URL=postgresql://repovil:repovil-local@localhost:5432/repovil \
  uv run pytest -m integration
uv run repovil-db-check
```

