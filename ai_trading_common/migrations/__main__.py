"""CLI entry point for ai_trading_common.migrations.

Invoked from each service's start.sh:

    python -m ai_trading_common.migrations apply --service <name> --dir <path>
    python -m ai_trading_common.migrations status --service <name> --dir <path>
    python -m ai_trading_common.migrations dry-run --service <name> --dir <path>
    python -m ai_trading_common.migrations reconcile --service <name> --dir <path>
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from ai_trading_common.migrations.runner import (
    MigrationRunner,
    discover_migrations,
)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai_trading_common.migrations")
    sub = p.add_subparsers(dest="cmd", required=True)

    common_args = lambda sp: (  # noqa: E731
        sp.add_argument("--service", required=True, help="Service name — used as key in schema_migrations + advisory lock"),
        sp.add_argument("--dir", required=True, type=Path, help="Path to migrations/ directory"),
        sp.add_argument("--database-url", default=None, help="Override $DATABASE_URL (or $MIGRATIONS_DATABASE_URL)"),
    )

    apply = sub.add_parser("apply", help="Apply all pending migrations (fail-fast)")
    common_args(apply)

    status = sub.add_parser("status", help="Show applied + pending migrations (read-only)")
    common_args(status)

    dryrun = sub.add_parser("dry-run", help="Discover + report pending without executing")
    common_args(dryrun)

    reconcile = sub.add_parser(
        "reconcile",
        help="Mark all discovered migrations as already-applied WITHOUT executing (BB-GA-4 greenfield adoption)",
    )
    common_args(reconcile)
    return p


def _resolve_database_url(override: str | None) -> str:
    if override:
        return override
    url = os.environ.get("MIGRATIONS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        sys.stderr.write(
            "FATAL: no database URL — pass --database-url, "
            "or set MIGRATIONS_DATABASE_URL or DATABASE_URL.\n"
        )
        sys.exit(2)
    return url


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    database_url = _resolve_database_url(args.database_url)

    if args.cmd == "dry-run":
        discovered = discover_migrations(args.dir)
        print(json.dumps(
            {"discovered": [{"id": m.migration_id, "checksum": m.checksum, "path": str(m.path)} for m in discovered]},
            indent=2,
        ))
        return 0

    runner = MigrationRunner(
        service_name=args.service,
        database_url=database_url,
        migrations_dir=args.dir,
    )

    try:
        if args.cmd == "apply":
            result = runner.apply_pending()
        elif args.cmd == "status":
            result = runner.status()
        elif args.cmd == "reconcile":
            result = runner.reconcile()
        else:  # pragma: no cover — argparse rejects unknown commands
            sys.stderr.write(f"unknown command: {args.cmd}\n")
            return 2
    except Exception as exc:
        sys.stderr.write(f"FATAL: {args.cmd} failed: {exc}\n")
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
