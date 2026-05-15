"""ai_trading_common.migrations — fail-fast SQL migration runner for AI-Trading-APP services.

Designed for BB-GA-4 (schema-drift safety net). Each service's start.sh calls
`python -m ai_trading_common.migrations apply --service <name> --dir <path>` BEFORE
exec uvicorn. The runner:

- Discovers *.sql files supporting both Flyway-style (V<n>__<slug>.sql) and
  numeric-prefix (NNN_<slug>.sql) naming conventions.
- Acquires a per-service Postgres advisory lock to serialize concurrent restarts
  of the same service. Different services run in parallel.
- Tracks applied migrations in a shared `schema_migrations` table on the same DB.
- Fails fast — non-zero exit if a migration errors, if a previously-applied file's
  checksum drifted (in-place edit detected), or if the bootstrap can't run.

See [specs/pe-backtesting-ga/design-bb-ga-4-schema-drift.md] for the full HLS.
"""
from __future__ import annotations

from ai_trading_common.migrations.runner import (
    Migration,
    MigrationRunner,
    apply_pending,
    discover_migrations,
    reconcile,
    status,
)

__all__ = [
    "Migration",
    "MigrationRunner",
    "apply_pending",
    "discover_migrations",
    "reconcile",
    "status",
]
