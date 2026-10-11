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

The Next.js server reads the FastAPI base URL from `REPOVIL_API_URL` (defaults to
`http://127.0.0.1:8000`). Ranking requests are made server-side; the browser does not
call GitHub or FastAPI directly.

The generic worker entry point is a configuration smoke check; collection jobs use
dedicated commands:

```bash
uv run repovil-worker
```

Validate the category/topic discovery configuration without changing data:

```bash
uv run repovil-categories-check
```

Apply the database migration and synchronize the validated category configuration:

```bash
uv run alembic upgrade head
uv run repovil-sync-categories
```

Run discovery and then bootstrap newly discovered repositories before tracking:

```bash
uv run repovil-discovery
uv run repovil-bootstrap
uv run repovil-tracking
```

The Railway daily cron runs discovery and bootstrap as one observable command:

```bash
uv run repovil-daily
```

Production images, project-wide Railway IaC, release ordering, environment variables,
and manual retry procedures are documented in
[`docs/RAILWAY_OPERATIONS.md`](docs/RAILWAY_OPERATIONS.md).

Validate the Railway IaC locally before planning changes against Railway:

```bash
npm ci
npm run iac:check
npm run iac:test
railway config plan
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
npm run iac:check
npm run iac:test
```

With PostgreSQL running, include the connection smoke test:

```bash
TEST_DATABASE_URL=postgresql://repovil:repovil-local@localhost:5432/repovil \
  uv run pytest -m integration
uv run repovil-db-check
```

