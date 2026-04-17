# migrations

Database migration files for the PostgreSQL Flexible Server that stores the runbook library, RBAC configuration, EOL cache, and platform settings.

## Contents

- `008_tenants.sql` — adds multi-tenant support columns to platform settings tables

Migrations are numbered sequentially and applied in order. Run migrations via `psql` or the project's migration runner before deploying new agent versions that depend on schema changes.
