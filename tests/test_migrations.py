"""Tests for ai_trading_common.migrations — discovery, sort order, advisory keys, runner orchestration.

Real-Postgres integration tests are deferred to BB-GA-4.2 (which provisions the
schema_migrations table on the test VPS). These tests cover the deterministic
parts of the runner using mocked psycopg + subprocess.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_trading_common.migrations.runner import (
    Migration,
    MigrationRunner,
    _advisory_lock_key,
    discover_migrations,
)


# ---------- Migration.from_path ----------

def _write(dir_: Path, name: str, body: str = "-- noop\n") -> Path:
    p = dir_ / name
    p.write_text(body)
    return p


def test_migration_parses_numeric_prefix_convention(tmp_path: Path) -> None:
    p = _write(tmp_path, "008_auth_security.sql")
    m = Migration.from_path(p)
    assert m.migration_id == "008_auth_security"
    assert m.sort_key == (0, 8, "auth_security")
    assert m.checksum.startswith("sha256:")
    assert m.checksum == "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def test_migration_parses_flyway_prefix_convention(tmp_path: Path) -> None:
    p = _write(tmp_path, "V12__create_users.sql")
    m = Migration.from_path(p)
    assert m.migration_id == "V12__create_users"
    assert m.sort_key == (0, 12, "create_users")


def test_migration_rejects_unparseable_filename(tmp_path: Path) -> None:
    p = _write(tmp_path, "not-a-migration.sql")
    with pytest.raises(ValueError, match="does not match supported conventions"):
        Migration.from_path(p)


# ---------- discover_migrations ----------

def test_discover_handles_missing_dir(tmp_path: Path) -> None:
    """No directory is a valid state — service has no migrations yet."""
    result = discover_migrations(tmp_path / "does-not-exist")
    assert result == []


def test_discover_returns_empty_for_empty_dir(tmp_path: Path) -> None:
    result = discover_migrations(tmp_path)
    assert result == []


def test_discover_sorts_numerically_not_lexicographically(tmp_path: Path) -> None:
    """`008_auth` must sort before `010_other`, not after `1_first`."""
    _write(tmp_path, "001_first.sql")
    _write(tmp_path, "010_tenth.sql")
    _write(tmp_path, "002_second.sql")
    result = discover_migrations(tmp_path)
    assert [m.migration_id for m in result] == ["001_first", "002_second", "010_tenth"]


def test_discover_mixes_flyway_and_numeric_convention(tmp_path: Path) -> None:
    """A service that started with Flyway naming and later switched (or vice-versa) is supported."""
    _write(tmp_path, "001_legacy.sql")
    _write(tmp_path, "V2__newer.sql")
    _write(tmp_path, "003_back_to_numeric.sql")
    result = discover_migrations(tmp_path)
    assert [m.migration_id for m in result] == ["001_legacy", "V2__newer", "003_back_to_numeric"]


def test_discover_excludes_rollback_scripts(tmp_path: Path) -> None:
    """Rollback/undo scripts living beside forward migrations must NOT be applied.

    The PE convention puts ``V<n>__rollback_<slug>.sql`` next to
    ``V<n>__create_<slug>.sql``; without exclusion, apply would run create then
    immediately the rollback and drop what it created.
    """
    _write(tmp_path, "V1__create_thing.sql")
    _write(tmp_path, "V1__rollback_create_thing.sql")
    _write(tmp_path, "V2__create_other.sql")
    _write(tmp_path, "V2__rollback_create_other.sql")
    result = discover_migrations(tmp_path)
    assert [m.migration_id for m in result] == ["V1__create_thing", "V2__create_other"]


def test_discover_ignores_non_sql_files(tmp_path: Path) -> None:
    _write(tmp_path, "001_real.sql")
    _write(tmp_path, "README.md", "# not a migration")
    _write(tmp_path, ".gitkeep", "")
    result = discover_migrations(tmp_path)
    assert [m.migration_id for m in result] == ["001_real"]


# ---------- advisory lock key derivation ----------

def test_advisory_lock_key_is_stable_per_service() -> None:
    """Same service name → same key. Required for serializing concurrent starts."""
    assert _advisory_lock_key("user-service") == _advisory_lock_key("user-service")


def test_advisory_lock_key_differs_per_service() -> None:
    """Different services → different keys → parallel-safe."""
    assert _advisory_lock_key("user-service") != _advisory_lock_key("prediction-engine")


def test_advisory_lock_key_fits_in_signed_bigint() -> None:
    """pg_advisory_xact_lock(bigint) — must be within [-(2^63), 2^63 - 1]."""
    key = _advisory_lock_key("any-service-name")
    assert -(2**63) <= key < 2**63


# ---------- MigrationRunner orchestration (mocked psycopg + subprocess) ----------

@pytest.fixture
def runner_factory(tmp_path: Path):
    """Build a MigrationRunner with a real migrations dir but mocked DB + psql calls."""
    def _factory(service: str = "user-service") -> MigrationRunner:
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        return MigrationRunner(
            service_name=service,
            database_url="postgresql://stub",
            migrations_dir=migrations_dir,
            applied_by="pytest",
        )
    return _factory


def _build_mock_conn(applied_rows: list[tuple[str, str]] | None = None) -> MagicMock:
    """A mock psycopg connection whose cursor returns the given (id, checksum) rows for the apply query."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = applied_rows or []
    conn.cursor.return_value.__enter__.return_value = cur
    conn.__enter__.return_value = conn
    return conn


def test_apply_pending_returns_empty_when_no_migrations(runner_factory) -> None:
    runner = runner_factory()
    with patch("ai_trading_common.migrations.runner._connect", return_value=_build_mock_conn()):
        result = runner.apply_pending()
    assert result == {"applied": [], "skipped": []}


def test_apply_pending_executes_only_unapplied_migrations(runner_factory) -> None:
    runner = runner_factory()
    _write(runner.migrations_dir, "001_a.sql", "CREATE TABLE a();")
    _write(runner.migrations_dir, "002_b.sql", "CREATE TABLE b();")

    m_a = Migration.from_path(runner.migrations_dir / "001_a.sql")
    mock_conn = _build_mock_conn(applied_rows=[(m_a.migration_id, m_a.checksum)])

    with patch("ai_trading_common.migrations.runner._connect", return_value=mock_conn), \
         patch("ai_trading_common.migrations.runner.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""
        result = runner.apply_pending()

    assert result["applied"] == ["002_b"]
    assert result["skipped"] == ["001_a"]
    assert run_mock.call_count == 1
    # Ensure psql was called with -v ON_ERROR_STOP=1 — non-negotiable
    args = run_mock.call_args.args[0]
    assert "-v" in args and "ON_ERROR_STOP=1" in args


def test_apply_pending_raises_on_checksum_drift(runner_factory) -> None:
    runner = runner_factory()
    _write(runner.migrations_dir, "001_a.sql", "CREATE TABLE a();")
    fake_old_checksum = "sha256:" + ("0" * 64)
    mock_conn = _build_mock_conn(applied_rows=[("001_a", fake_old_checksum)])

    with patch("ai_trading_common.migrations.runner._connect", return_value=mock_conn):
        with pytest.raises(RuntimeError, match="Checksum drift"):
            runner.apply_pending()


def test_apply_pending_records_failure_then_reraises(runner_factory) -> None:
    runner = runner_factory()
    _write(runner.migrations_dir, "001_bad.sql", "INVALID SQL;")
    mock_conn = _build_mock_conn(applied_rows=[])

    with patch("ai_trading_common.migrations.runner._connect", return_value=mock_conn), \
         patch("ai_trading_common.migrations.runner.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 1
        run_mock.return_value.stderr = "ERROR: syntax error"
        with pytest.raises(RuntimeError, match=r"psql exited 1"):
            runner.apply_pending()

    # The failure-record INSERT should have been issued before re-raise
    cur = mock_conn.cursor.return_value.__enter__.return_value
    insert_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO schema_migrations" in c.args[0]
    ]
    assert len(insert_calls) == 1, "expected one failure-record INSERT before re-raise"
    inserted_success_flag = insert_calls[0].args[1][5]
    assert inserted_success_flag is False


def test_reconcile_records_without_executing(runner_factory) -> None:
    runner = runner_factory()
    _write(runner.migrations_dir, "001_existing.sql", "CREATE TABLE existing();")
    _write(runner.migrations_dir, "002_also_existing.sql", "CREATE TABLE also();")
    mock_conn = _build_mock_conn(applied_rows=[])

    with patch("ai_trading_common.migrations.runner._connect", return_value=mock_conn), \
         patch("ai_trading_common.migrations.runner.subprocess.run") as run_mock:
        result = runner.reconcile()

    assert result["reconciled"] == ["001_existing", "002_also_existing"]
    assert result["already_recorded"] == []
    # The whole point of reconcile: psql is NOT invoked
    run_mock.assert_not_called()
