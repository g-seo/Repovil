# Agent Instructions

## Source of Truth

- Product requirements: docs/PRD.md
- Implementation progress: docs/IMPLEMENTATION_PLAN.md
- PRD is the source of truth for product behavior.
- Consult relevant PRD sections before implementing features.
- Do not silently change product requirements.
- Ask before making decisions that affect product behavior.

## Tech Stack

- Backend: Python, FastAPI, uv
- Frontend: Next.js, TypeScript, npm
- Database: PostgreSQL
- Migrations: Alembic
- Local database: Docker Compose
- Deployment: Railway
- Scheduling: Railway Cron

Do not introduce Redis, Celery, Kafka,
Kubernetes, or unnecessary dependencies.

## Architecture Rules

- GitHub API access must go through GitHubClient.
- Only background workers communicate with GitHub.
- User-facing APIs read from PostgreSQL.
- Keep discovery and tracking responsibilities separate.
- Tracking and ranking form one controlled pipeline.
- Use github_id as the repository identity.
- Store all timestamps in UTC.
- Never treat stale snapshots as fresh data.
- Preserve historical snapshots.
- Follow ranking and publication policies in PRD.

## Development Workflow

- Follow docs/IMPLEMENTATION_PLAN.md for planned work.
- Implement one phase at a time unless requested otherwise.
- Before editing, inspect the relevant existing code.
- Prefer simple solutions over premature abstractions.
- Keep changes limited to the current task.
- Do not implement future or out-of-scope features.
- Avoid unrelated refactoring.
- Update implementation progress after completing a phase.

## Quality

- Add tests for new business logic.
- Test edge cases and failure scenarios.
- Run relevant tests, linting, and type checks.
- Fix failures caused by your changes.
- Never claim tests passed unless executed.
- Keep database schema changes in Alembic migrations.

## Safety

- Never commit secrets or .env files.
- Never modify production data without approval.
- Do not push, deploy, or execute destructive
  operations without explicit approval.
- Do not overwrite unrelated user changes.

## Completion Report

After each task, briefly report:
- What changed
- Tests executed and results
- Remaining issues or blockers
- Implementation plan updates