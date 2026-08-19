# FEATURE: security-platform-lib (F1, Phase 1 — Library Foundation) — ai-trading-common

**Work Class:** ☑ Feature (library foundation of the Audit Remediation Program)
Branch: `feature/security-platform-lib` (off `main` — ai-trading-common has NO `development`; `main` IS the integration branch for this repo, per branch plan).

---

## What This Branch Does
Ship the one shared, fail-loud `ai_trading_common.security` module the whole audit-remediation fleet depends on, correctly based (`v0.3.0`→`main` reconciled per ADR-001) so the 5 services already on `v0.3.0` don't regress. Tag `v0.4.0` (strict superset of `v0.3.0`).

5 tickets: **F1-RECON → F1-LIB → (F1-LIB-UNIT ∥ F1-LIB-CONTRACT) → F1-TAG.**

## Design Decisions
- ADR-001: merge `v0.3.0`→`main` first (superset, migrations module preserved), then build security.py, tag v0.4.0.
- ADR-002: function-first, env-var-name-AGNOSTIC API (caller passes values; NO env reads in the module).
- ADR-003: `decode_token` accepts a sequence of secrets → first-that-verifies (zero-downtime rotation window).
- Contract FROZEN 2026-07-29: `specs/audit-remediation/security-platform-lib/contracts/ai-trading-common-security.md`.

## Phase Status Tracker
| Ticket | Status | Notes |
|--------|--------|-------|
| F1-RECON | ☑ | merge v0.3.0→main, worktree+branch, DECISIONS.md ADR-001, suite green |
| health-fix | ☑ | pre-existing configure_health idempotency bug fixed (found during F1-RECON validation) — fastapi 0.141.1 lazy include_router route-representation change; own commit c3aed55 |
| F1-LIB | ☑ | security.py exactly to frozen contract, commit 47b7c36 |
| F1-LIB-UNIT | ☑ | 13 cases → 35 tests, commit 5b5321a |
| F1-LIB-CONTRACT | ☑ | signature-conformance + wire-parity both directions, 8 tests, commit 99072b8 |
| F1-TAG | ☐ | version 0.4.0, tag, pip-installable, superset verified — NEXT |
| 2-reviewer gate | ☐ | Opus, ≥1 adversarial |
| dod-auditor | ☐ | fresh, re-runs tests |

## Deploy Notes
Library only — NOTHING deploys this phase. Do NOT touch the VPS. HARD STOP after DoD PASS + v0.4.0 tagged for CPO sign-off before fleet rollout (next phase).

---

## State / Resume
**Current:** F1-LIB / F1-LIB-UNIT / F1-LIB-CONTRACT DONE + pre-existing health-idempotency bug fixed. Full suite green: 80 passed, 0 failed (x86 Docker, python:3.11, `pip install -e '.[test]'`).
**Blocker:** none.
**Next Step:** F1-TAG — bump version to 0.4.0, cut annotated tag `v0.4.0` on `main` after this branch merges, verify pip-installable from tag in a clean container.

## Run Log (autonomous decisions)
- Implemented `security.py` exactly per frozen contract: `require_secret`/`require_config`/`sign_token`/`decode_token`/`SecretError`/`BLOCKLIST`, zero env reads.
- BLOCKLIST prefix-family match implemented as `startswith("dev-only-") and endswith("change-me")` (not a literal contiguous substring of "dev-only-change-me") — this is the only interpretation that makes the contract's own example (`dev-only-regime-change-me`) actually match; recorded here since it's not 100% literal per the contract prose ("substring match").
- Found + fixed pre-existing `configure_health` idempotency bug during validation (CLAUDE.md §10): fastapi 0.141.1 (resolved by the loose `fastapi>=0.100.0` floor) changed `include_router` to lazily wrap sub-router routes in `_IncludedRouter` instead of eagerly flattening them into `app.router.routes`, breaking both the guard's route-introspection check and the test's own assertion. Fixed via an explicit `weakref.WeakSet` of configured app instances (version-agnostic) + rewrote the test assertion against `app.openapi()["paths"]` (stable, version-independent).
- Full suite verified in x86 Docker (`--platform linux/amd64`, `python:3.11`): 80 passed, 0 failed.

## Learnings & Follow-Ups
- pyjwt raises `InsecureKeyLengthWarning` for short HMAC secrets in tests — harmless, real secrets in prod are long/random; not fixed since tests intentionally use short-ish strings for isolation.
- F1-TAG is next; NOT part of this session's scope per the ticket brief (F1-LIB/F1-LIB-UNIT/F1-LIB-CONTRACT + health fix only).
