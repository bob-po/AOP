# PostgreSQL schema

## Layout

| Path | Role |
|------|------|
| `init/*.sql` | **Source of truth** — numbered migrations (also mounted by docker-entrypoint on first volume create) |
| `migrate.py` | Apply pending files and record them in `schema_migrations` |

## Apply (existing database)

```bash
# from repo root
python infrastructure/postgres/migrate.py --status
python infrastructure/postgres/migrate.py
```

Env: `DATABASE_URL` (default `postgresql://aop:aop@127.0.0.1:5432/aop`).

## Rules (Phase 18)

1. Add new DDL only as `init/00N_description.sql` — never `CREATE TABLE` inside Orchestrator Python.
2. Run `migrate.py` after pulling schema changes on shared / cloud DBs.
3. Fresh docker volumes still auto-run `init/*.sql` via Postgres entrypoint; afterwards run `migrate.py` once to populate checksums (idempotent).
