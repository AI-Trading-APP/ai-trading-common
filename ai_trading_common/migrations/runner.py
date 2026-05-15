"""Core migration runner — discovery, locking, apply algorithm."""
from __future__ import annotations

import getpass
import hashlib
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# psycopg is imported lazily — the lib core is dependency-free, services
# that don't use migrations don't pay the cost.
_NUMERIC_PREFIX = re.compile(r"^(\d+)[_-](.+)$")
_FLYWAY_PREFIX = re.compile(r"^V(\d+)__(.+)$")
_BOOTSTRAP_SQL_PATH = Path(__file__).parent / "bootstrap.sql"


@dataclass(frozen=True)
class Migration:
    """A discovered SQL migration file.

    `migration_id` is the filename stem (e.g. "008_auth_security" or "V1__create_backtest_results")
    and is the natural key inside `schema_migrations`. `sort_key` is the lexicographic
    ordering tuple — leading numeric first, then alphabetical tiebreak.
    """

    path: Path
    migration_id: str
    sort_key: tuple[int, int, str]
    checksum: str = field(repr=False)

    @classmethod
    def from_path(cls, path: Path) -> "Migration":
        stem = path.stem
        if (m := _FLYWAY_PREFIX.match(stem)) is not None:
            n, slug = int(m.group(1)), m.group(2)
        elif (m := _NUMERIC_PREFIX.match(stem)) is not None:
            n, slug = int(m.group(1)), m.group(2)
        else:
            raise ValueError(
                f"Migration filename does not match supported conventions "
                f"(V<n>__<slug>.sql or <NNN>_<slug>.sql): {path.name}"
            )
        body = path.read_bytes()
        checksum = "sha256:" + hashlib.sha256(body).hexdigest()
        return cls(path=path, migration_id=stem, sort_key=(0, n, slug), checksum=checksum)


def discover_migrations(migrations_dir: Path) -> list[Migration]:
    """Returns all *.sql files in the dir, sorted deterministically.

    No directory or zero files is a valid state — returns []. Callers decide
    whether that is OK (it is, for services that have no migrations yet).
    """
    if not migrations_dir.exists() or not migrations_dir.is_dir():
        return []
    migrations = [Migration.from_path(p) for p in sorted(migrations_dir.glob("*.sql"))]
    migrations.sort(key=lambda m: m.sort_key)
    return migrations


def _connect(database_url: str):
    """Lazy-import psycopg and connect. Raises on missing dependency with a clear message."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required for migrations. Install ai-trading-common[migrations] "
            "or add `psycopg[binary]>=3.1` to your service's dependencies."
        ) from exc
    return psycopg.connect(database_url, autocommit=False)


def _advisory_lock_key(service_name: str) -> int:
    """Stable 64-bit signed integer key for pg_advisory_xact_lock.

    Different services get different keys → parallel-safe. Same service restarts
    serialize behind the same key.
    """
    h = hashlib.blake2b(f"migrations:{service_name}".encode(), digest_size=8).digest()
    # Treat as signed int64 — pg_advisory_xact_lock(bigint) accepts negative too.
    return int.from_bytes(h, "big", signed=True)


@dataclass
class MigrationRunner:
    """Encapsulates a single apply/status/reconcile session."""

    service_name: str
    database_url: str
    migrations_dir: Path
    applied_by: str = field(default_factory=getpass.getuser)
    bootstrap_sql_path: Path = field(default=_BOOTSTRAP_SQL_PATH)

    def bootstrap(self) -> None:
        """Idempotently create the schema_migrations table.

        Uses a fixed bootstrap advisory key so multiple services racing on
        first-ever start don't double-CREATE. CREATE TABLE IF NOT EXISTS is
        already idempotent, the lock just suppresses noise.
        """
        with _connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (_advisory_lock_key("_bootstrap"),))
                sql = self.bootstrap_sql_path.read_text()
                cur.execute(sql)
            conn.commit()
        logger.info("migrations.bootstrap_ok service=%s", self.service_name)

    def _fetch_applied(self, conn) -> dict[str, str]:
        """Returns {migration_id: checksum} for all rows where success=true."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT migration_id, file_checksum FROM schema_migrations "
                "WHERE service_name = %s AND success = TRUE "
                "ORDER BY applied_at",
                (self.service_name,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}

    def _record(
        self,
        conn,
        migration: Migration,
        *,
        success: bool,
        duration_ms: int,
        error_message: Optional[str] = None,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schema_migrations "
                "(service_name, migration_id, file_checksum, applied_by, "
                " duration_ms, success, error_message) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    self.service_name,
                    migration.migration_id,
                    migration.checksum,
                    self.applied_by,
                    duration_ms,
                    success,
                    error_message,
                ),
            )

    def _execute_sql_file(self, sql_path: Path) -> None:
        """Run a .sql file via the psql binary so DO $$ blocks + COPY work.

        Inherits the connection identity from PGURL / PG* env vars set by the
        caller; we pass `--set ON_ERROR_STOP=1` so the runner sees failures.
        """
        env_url = self.database_url
        proc = subprocess.run(
            ["psql", env_url, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(sql_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"psql exited {proc.returncode} for {sql_path.name}:\n{proc.stderr.strip()}"
            )

    def apply_pending(self) -> dict[str, list[str]]:
        """Apply all discovered migrations not yet in schema_migrations.

        Returns a dict {"applied": [...], "skipped": [...]} for the caller to log.
        Raises on:
          - psycopg not installed
          - psql binary not available
          - any migration SQL error
          - checksum drift on a previously-applied migration
        """
        self.bootstrap()

        discovered = discover_migrations(self.migrations_dir)
        if not discovered:
            logger.info("migrations.no_pending service=%s dir=%s", self.service_name, self.migrations_dir)
            return {"applied": [], "skipped": []}

        applied_ids: list[str] = []
        skipped_ids: list[str] = []

        with _connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (_advisory_lock_key(self.service_name),),
                )
            applied_set = self._fetch_applied(conn)

            for migration in discovered:
                if migration.migration_id in applied_set:
                    if applied_set[migration.migration_id] != migration.checksum:
                        raise RuntimeError(
                            f"Checksum drift on already-applied migration "
                            f"{migration.migration_id}: file is {migration.checksum} "
                            f"but {applied_set[migration.migration_id]} was recorded. "
                            f"Was the migration file edited in place after apply? "
                            f"Add a new forward migration to fix; do not edit history."
                        )
                    skipped_ids.append(migration.migration_id)
                    continue

                start = time.monotonic()
                try:
                    self._execute_sql_file(migration.path)
                except Exception as exc:  # noqa: BLE001 — re-raised after recording
                    duration_ms = int((time.monotonic() - start) * 1000)
                    self._record(
                        conn,
                        migration,
                        success=False,
                        duration_ms=duration_ms,
                        error_message=str(exc),
                    )
                    conn.commit()  # commit the failure record so it's auditable
                    logger.error(
                        "migrations.failed service=%s id=%s dur_ms=%d err=%s",
                        self.service_name,
                        migration.migration_id,
                        duration_ms,
                        exc,
                    )
                    raise

                duration_ms = int((time.monotonic() - start) * 1000)
                self._record(conn, migration, success=True, duration_ms=duration_ms)
                applied_ids.append(migration.migration_id)
                logger.info(
                    "migrations.applied service=%s id=%s dur_ms=%d",
                    self.service_name,
                    migration.migration_id,
                    duration_ms,
                )

            conn.commit()

        return {"applied": applied_ids, "skipped": skipped_ids}

    def status(self) -> dict[str, list[dict]]:
        """Read-only inspector — returns applied + pending migrations.

        Does NOT bootstrap; if the table doesn't exist yet, the applied list is
        empty and every discovered file is pending.
        """
        discovered = discover_migrations(self.migrations_dir)
        applied_rows: list[dict] = []

        try:
            with _connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT migration_id, file_checksum, applied_at, duration_ms, success "
                        "FROM schema_migrations "
                        "WHERE service_name = %s "
                        "ORDER BY applied_at DESC",
                        (self.service_name,),
                    )
                    applied_rows = [
                        {
                            "migration_id": r[0],
                            "checksum": r[1],
                            "applied_at": r[2].isoformat() if r[2] else None,
                            "duration_ms": r[3],
                            "success": r[4],
                        }
                        for r in cur.fetchall()
                    ]
        except Exception as exc:  # noqa: BLE001 — status must not raise; report bootstrap_missing
            logger.debug("migrations.status_no_table service=%s err=%s", self.service_name, exc)

        applied_ids = {r["migration_id"] for r in applied_rows if r["success"]}
        pending = [
            {"migration_id": m.migration_id, "checksum": m.checksum, "path": str(m.path)}
            for m in discovered
            if m.migration_id not in applied_ids
        ]
        return {"applied": applied_rows, "pending": pending}

    def reconcile(self) -> dict[str, list[str]]:
        """Mark all discovered migrations as already-applied without executing them.

        For greenfield BB-GA-4 adoption: existing schemas were hand-applied during
        the manual operator era; we need to record them in schema_migrations so the
        runner doesn't try to re-execute. NEVER use this after the canonical
        pipeline is live — it bypasses verification.
        """
        self.bootstrap()
        discovered = discover_migrations(self.migrations_dir)
        recorded: list[str] = []
        already: list[str] = []
        with _connect(self.database_url) as conn:
            applied_set = self._fetch_applied(conn)
            for migration in discovered:
                if migration.migration_id in applied_set:
                    already.append(migration.migration_id)
                    continue
                self._record(conn, migration, success=True, duration_ms=0,
                             error_message="reconciled — file not actually executed")
                recorded.append(migration.migration_id)
            conn.commit()
        return {"reconciled": recorded, "already_recorded": already}


def apply_pending(service_name: str, database_url: str, migrations_dir: Path) -> dict:
    """Module-level convenience wrapper around MigrationRunner.apply_pending."""
    return MigrationRunner(service_name, database_url, migrations_dir).apply_pending()


def status(service_name: str, database_url: str, migrations_dir: Path) -> dict:
    return MigrationRunner(service_name, database_url, migrations_dir).status()


def reconcile(service_name: str, database_url: str, migrations_dir: Path) -> dict:
    return MigrationRunner(service_name, database_url, migrations_dir).reconcile()
