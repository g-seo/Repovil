# MVP Release Checklist

This checklist operationalizes the MVP acceptance work in Phase 14. Product behavior
remains defined by `docs/PRD.md`; deployment procedures remain in
`docs/RAILWAY_OPERATIONS.md`.

## Before a release

- [ ] Review `git status --short` and the Railway IaC plan. Do not apply a plan with an
  unexpected destroy or an environment other than the intended one.
- [ ] Run the complete backend suite with `TEST_DATABASE_URL`, plus `uv run ruff check .`
  and `uv run mypy`.
- [ ] Run frontend test, lint, type-check, and production build commands from `README.md`.
- [ ] Run `npm run iac:check` and `npm run iac:test`.
- [ ] Confirm migration forward/backward smoke tests pass and PostgreSQL backup/PITR is
  available before applying an environment with data that matters.
- [ ] Confirm `GITHUB_TOKEN` is supplied only as a Railway shared variable and API/web
  services do not receive it.

## After a staging deployment

- [ ] Verify API `/health` and `/ready`, plus web `/`, return HTTP 200.
- [ ] Verify categories list all six active categories, including categories with no result.
- [ ] Run the daily pipeline once and inspect its discovery/bootstrap status and failure
  ranges; retry only recorded failed ranges after the underlying cause is resolved.
- [ ] Run tracking once, then use a new database connection to verify that `published_at`
  and ranking rows persist. Confirm `/rankings` returns that `tracking_run_id`.
- [ ] Exercise All/category and `24h`/`7d`/`30d` filters, pagination, repository detail,
  and the actual-versus-estimated graph legend.
- [ ] After at least 24 hours of real snapshots, verify a 24h ranking uses actual baseline
  data. The automated acceptance fixture covers this time interval without waiting.
- [ ] Inspect JSON logs for failed repository/range events and confirm no token, database
  URL, or authorization header is present.

## Rollback and incident response

- Stop the rollout and inspect health/readiness and worker logs if pre-deploy migration,
  category sync, or a worker command fails.
- Redeploy only a previously validated image that is compatible with the current schema.
  Do not run an ad-hoc production Alembic downgrade.
- If schema or data restoration is required, use the approved PostgreSQL backup/PITR
  process with explicit authorization. Preserve snapshots, bootstrap history, and run
  records during investigation.
- For a partial or failed discovery/tracking run, follow the targeted retry commands in
  `docs/RAILWAY_OPERATIONS.md`; a failed run must not be made to look published.

## Known MVP limitations

- GitHub Search cannot guarantee a complete global inventory. Overfull, incomplete, and
  rate-limited ranges remain recorded for retry rather than being treated as success.
- Bootstrap values are estimates: GitHub history reports star creations, cannot restore
  unstars, and does not guarantee UTC day boundaries. They never qualify a repository for
  24h ranking.
- A new repository needs a valid actual snapshot at least 24 hours before it can enter a
  24h ranking. It can use valid bootstrap estimates for 7d/30d meanwhile.
- There is intentionally no login, watchlist, alerting, recommendation, LLM
  categorization, admin UI, GraphQL tracking, or snapshot downsampling in the MVP.
