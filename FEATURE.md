# Feature: Platform Reliability P1 — Block 0 Taxonomy

**Branch:** feature/platform-reliability-taxonomy  
**Repo:** ai-trading-common  
**Commit:** fd64bee  
**Last updated:** 2026-07-03

---

## Done

- **COM-1** — `CauseCategory` StrEnum added to `ai_trading_common/errors.py` with 7 values:
  `timeout`, `quota`, `out-of-universe`, `IP-block`, `breaker-open`, `stale-data`, `unknown`.
  Re-exported from `ai_trading_common/__init__.py`.

- **COM-2** — `configure_health(app, name, ver)` / `configure_health(name, ver)` dual-signature
  shim in `health.py`. Idempotency guard fixed to use `original_router is health_router` identity
  check (FastAPI wraps included routers as `_IncludedRouter` objects; path-based check was broken).
  `/health/ready` dep-result now includes `cause_category` + `last_known_good_ts` when a dep
  check returns them in the optional third tuple element.

- **TEST-1** — `tests/test_reliability_taxonomy.py` created and passing (20 new tests).
  Full suite: **52 passed, 0 failed** (pytest tests/ -q in python:3.11-slim Docker).

---

## Key Decisions

- Used `StrEnum` (Python 3.11 stdlib) instead of `str, Enum` mixin — Python 3.11 changed
  `str(StrMixinEnum.MEMBER)` to return `'ClassName.MEMBER'` not the value; `StrEnum` gives the
  expected behavior (`str(member) == member.value`).
- Idempotency in `configure_health` uses `getattr(route, "original_router", None) is health_router`
  — the `_IncludedRouter` dataclass (FastAPI internal) exposes the original router via this attr.
  Tests updated to match the same idiom.
- `cause_category` serialised via `str()` (works for both `CauseCategory` enum and raw strings)
  in both `_json_error_response` and `DependencyCheck.run_all`.
- **Block 0 PRs target `development` branch** (ai-trading-common has no release branch; other
  services have independent release flows).
- Block 1 (adminserv + admin-app) built in parallel (independent, no COMANticipated on Block 0 merge).
- All work is additive and backward-compatible (shim dual-signature preserves existing code paths).

---

## Next

**PAUSED at Block 3 scope gate, pending owner scope decision.**

If proceeding with full P1 console (Block 3):

1. Block 0 (COM-1/COM-2/TEST-1) **MUST merge to `development` FIRST** — submit PR from this branch,
   pass 2-reviewer gate (§2 SDLC), then merge.
2. Once Block 0 merged to development: Block 1 (adminserv + admin-app) PRs open → 2-reviewer → merge.
3. Then Block 3a–3f proceed per `specs/platform-reliability/roadmap.md` (health-wiring across 4 services,
   adminserv console backend endpoints, admin-app UI build-out, E2E validation, deploy + staging verification).

If deferring P1 console: keep this branch alive; no close-out. Reopen when scope is decided.

---

## Resume Pointer

**Worktree:** `/Users/kasireddy/Personal_Projects/AI-Trading-APP/ai-trading-common-feat-platform-reliability-taxonomy`  
**Branch:** `feature/platform-reliability-taxonomy`  
**Commit:** `fd64bee`  
**Next session:** read this file, then `git log development..HEAD` to see all commits on this branch.  
**Spec context:** `specs/platform-reliability/design.md` Block 0 section.

All code + tests committed. No DB migrations. TypeScript mirror (aitradingnode/lib/types/causeCategory.ts)
created but uncommitted in aitradingnode (separate repo, independent feature branch).
