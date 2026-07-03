# Feature: Platform Reliability P1 — Block 0 Taxonomy

**Branch:** feature/platform-reliability-taxonomy  
**Repo:** ai-trading-common  
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

---

## Next

1. Open PR from `feature/platform-reliability-taxonomy` → `development`.
2. 2-reviewer gate (2 reviewers must approve before merge per project protocol).
3. After merge: archive this file → `docs/features/platform-reliability-taxonomy.md`.
4. Release lock in `.coordination/locks.md` if claimed.

---

## Resume Pointer

All code + tests committed on this branch. No DB migrations required. No frontend changes.
Start a fresh session by reading this file and running `git log development..HEAD`.
