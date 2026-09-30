# Veles-MOEX — REPORT: MVP-6.11 REV2 (round-2 correction)

## Correction commit

1. `e026886dfdc6f98112dfc214060c5fc2bb2ae075` — "review: implement MVP-6.11
   round-2 correction (B2 fresh deposit read)" (correction on
   `agent/review/mvp-6.11`).

- Round-1 correction reviewed: `a6aaba5` (REV1). Round-2 review:
  `.agent/REVIEW-MVP-6.11.md` (REJECTED, B2). B1 and C7 are closed; the
  round-1 findings and accepted contracts are unchanged.
- Base before MVP-6.11: `master @ 10d445e0af61c617d7484ca38d79a94cb45b0aa0`.
- Correction HEAD on the review branch: `e026886dfdc6f98112dfc214060c5fc2bb2ae075`
  (pushed to GitHub, in sync with `origin/agent/review/mvp-6.11`).
- No changes to `master`; publication requires independent acceptance
  (round-3 decision).

## What changed (B2)

### B2. The C6 deposit provider reads the current database value

Round-2 review finding: `build_live_service()` wired `_deposit_provider` →
`bot_repository.get(bot_id)` → `AsyncSession.get(Bot, id)` on the long-lived
live-service session (`expire_on_commit=False`). Once that session has loaded
the `Bot`, `Session.get()` returns the identity-map instance without querying
the database, while `PATCH /api/bots/{id}` writes through a different
per-request session — so a deposit edit never reached the engine in
production.

- `backend/app/bots/repository.py`: new `BotRepository.get_deposit(bot_id)`
  reads the row with `session.get(Bot, bot_id, populate_existing=True)` — a
  fresh database read on every call, independent of the identity-map state.
- `backend/app/trading/live_execution.py`: the provider is extracted from the
  `build_live_service()` closure into the testable module-level
  `make_deposit_provider(bot_repository, bot_id)` (returns an async callable
  that calls `bot_repository.get_deposit(bot_id)`); `build_live_service()`
  now wires `deposit_provider=make_deposit_provider(bot_repository, bot_id)`.
  The API session model is unchanged.
- `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md §29` updated (C6 section):
  a single sentence on the fresh database read (`populate_existing=True`,
  `expire_on_commit=False` identity-map caveat, review correction B2), plus
  the B2 regression listed in the Testing paragraph.

## Regression / new tests

- `backend/tests/test_mvp611_deposit_sizing.py` (38 tests; +1 B2):
  `test_production_deposit_provider_reads_fresh_value_after_other_session_commit` —
  two **real** `AsyncSession`s over a file-based `sqlite+aiosqlite` database
  (each session gets its own connection, as in production with PostgreSQL;
  only the `Bot` table is created; `aiosqlite` is a dev-only dependency):
  1. Session A (long-lived live session, `expire_on_commit=False`) loads the
     bot at 10000 and commits its read transaction (the live session commits
     between cycles);
  2. Session B (per-request API session) updates the deposit to 20000 with
     the existing `BotRepository.update_deposit`;
  3. a plain `get` on session A still returns the stale 10000 (identity-map
     copy), while `make_deposit_provider(session_a_repo, 1)()` — the same
     function the production wiring uses — returns 20000;
  4. the same provider sees a clearing edit (None through session B) — the
     next FLAT entry is blocked with `SizingNotConfigured`.

Determinism note: the Session identity map is a `WeakInstanceDict`, so the
test holds a strong reference to the loaded `Bot` in session A — otherwise a
plain `get` silently re-reads the row once the transient result is garbage
collected and the staleness scenario cannot be reproduced. The test asserts
the staleness (plain `get` returns 10000) to prove the provider's
`populate_existing` read is what makes the edit visible.

## Validation (round 3)

| Check | Result |
|---|---|
| `pytest` (backend, full) | **412 passed, 1 skipped** |
| `ruff check app tests scripts` | **All checks passed** |
| frontend | no frontend diff since round 1 (build verified in round 1) |

## State

- `agent/review/mvp-6.11` committed and pushed (`e026886dfdc…`).
- `agent/control` carries this report; `PROJECT_STATE.md` updated (round 3,
  awaiting decision).
- `master` unchanged. Issue #3 open pending publication.

**No self-declaration of acceptance.**
