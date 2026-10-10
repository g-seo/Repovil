# Category seed/sync command contract

This contract defines the database behavior that Phase 4 will implement for the
validated `config/categories.yaml` document. Product behavior remains governed by
`docs/PRD.md` and decision CAT-06 in `docs/MVP_ACCEPTANCE_CRITERIA.md`.

## Command boundary

- The command will be exposed as `uv run repovil-sync-categories` in Phase 4.
- It loads and fully validates the YAML before opening a write transaction.
- A read, parse, validation, or database error exits non-zero and commits no changes.
- Re-running the command with the same file produces the same active rows and mappings,
  without duplicate categories, topics, or category/topic relationships.

## Identity and updates

- Category identity is its stable `slug`; its name, active flag, and display order are
  updated from YAML.
- Topic identity is its validated GitHub topic `name`. Phase 3 performs no implicit
  normalization, so the validated YAML value is the stored identity.
- Category/topic relationships exactly follow the validated YAML for active configured
  records.
- `All` is never inserted as a category or topic.

## Removal and reactivation

- A category or topic missing from a later YAML file is soft-deactivated; historical
  rows and repository relationships are preserved.
- A relationship removed from YAML is made inactive without deleting its history. The
  Phase 4 schema must therefore represent mapping activity if a hard delete would lose
  that history.
- Re-adding a previously removed category, topic, or relationship reactivates its
  existing row rather than creating a replacement.
- The complete sync is one PostgreSQL transaction, so readers observe either the prior
  configuration or the fully applied new configuration.
