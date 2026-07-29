# ai-trading-common — Architecture Decision Log

Append-only. Never edit past rows; supersede with a new row referencing the old ID.

---

## ADR-001 — base-branch reconciliation for the security module

- **Date:** 2026-07-29
- **Feature:** F1 `security-platform-lib` (REQ-010 / US-8 / Gap G8)
- **Decision:** Merge tag `v0.3.0` into `main` first (superset merge, preserving the
  migrations module byte-unchanged), THEN build `security.py` on the reconciled `main`,
  and tag the result `v0.4.0`. `v0.4.0` is a strict superset of `v0.3.0`
  (migrations module unchanged + new security module).
- **Rationale:** `main` (v0.2.3) had diverged from `v0.3.0` (migrations-runner module,
  PR #5, ~492 lines) — `git merge-base --is-ancestor v0.3.0 main` was false. 5 services
  already consume `v0.3.0`; building new work on stale `main` and cutting a tag from it
  would silently un-ship the migrations module to those services on next pin bump.
- **Supersedes:** none (first entry in this log).
