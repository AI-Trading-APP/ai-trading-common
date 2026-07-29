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
| F1-RECON | ☐ | merge v0.3.0→main, worktree+branch, DECISIONS.md ADR-001, suite green |
| F1-LIB | ☐ | security.py exactly to frozen contract |
| F1-LIB-UNIT | ☐ | 13 guard/rotation cases |
| F1-LIB-CONTRACT | ☐ | signature-conformance + wire-parity both directions |
| F1-TAG | ☐ | version 0.4.0, tag, pip-installable, superset verified |
| 2-reviewer gate | ☐ | Opus, ≥1 adversarial |
| dod-auditor | ☐ | fresh, re-runs tests |

## Deploy Notes
Library only — NOTHING deploys this phase. Do NOT touch the VPS. HARD STOP after DoD PASS + v0.4.0 tagged for CPO sign-off before fleet rollout (next phase).

---

## State / Resume
**Current:** Phase 1 execution starting (F1-RECON).
**Blocker:** none.
**Next Step:** F1-RECON — reconcile v0.3.0→main in a worktree, verify green in x86 Docker python.

## Run Log (autonomous decisions)
- (to be appended as tickets complete)

## Learnings & Follow-Ups
- (to be filled at ship)
