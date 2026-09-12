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

## ADR-002 — `main` is the single trunk; `development` reconciled and retired

- **Date:** 2026-09-13
- **Feature:** certify-remote fan-out, Ticket B (blocklist) — triage of the branch divergence
- **Decision:** `main` is the integration AND release branch for this library. Features
  branch off `main`, land via a §2b-gated PR to `main`, and releases are version tags cut
  from `main`. No `development`/`release` branches for this repo — a deliberate, recorded
  exception to the workspace default ("use `development` if it exists"), because nothing
  deploys this repo: consumers pin tags, so the tag IS the release.
- **Rationale:** after ADR-001 moved the trunk to `main`, `development` (still the GitHub
  default) kept receiving work (#5, #6, #9) that never reached a tag; `origin/development`
  and `origin/main` diverged both ways. Content audit: `main` already carried everything
  on `development` except `tests/test_reliability_taxonomy.py`; porting that file exposed
  two real Block-0 contract gaps on `main` (CauseCategory not a StrEnum; `configure_health`
  lost the name-first style) — fixed in this same PR. 16/19 consumer pins are v0.4.x
  (all from `main`); no released tag ever contained `development`'s Block-0 commit.
- **Follow-through (owner, GitHub settings):** set the default branch to `main`; then
  fast-forward `development` to `main` or delete it — never keep two trunks.
- **Supersedes:** ADR-001's implicit "development still exists" state; ADR-001's decision
  itself stands.
