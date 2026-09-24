# Veles-MOEX — REPORT: MVP-6.6 Risk Manager Execution Preconditions

## Summary

MVP-6.6 is implemented: `RiskManager.check_order()` now enforces the full set of
broker-neutral execution preconditions required by the architecture, without
bypassing the MVP-6.5 bot lifecycle gate.

- Implementation commit (master): `3231a51384f968fb6b1c138cf939bacf21b4c81b`
- Review branch: `agent/review/mvp-6.6` (HEAD = `3231a51`)
- **master was NOT pushed** (local master only, per task instructions).

## Exact implemented checks

`RiskManager.check_order()` (backend/app/trading/risk_manager.py), in order:

1. **Emergency stop** — active flag rejects all orders (pre-existing).
2. **Positive quantity** — `quantity <= 0` is rejected (zero and negative).
3. **Valid LIMIT price** — LIMIT intents must carry a positive `limit_price`;
   MARKET intents do not require one (previously unchecked).
4. **Instrument/trading permission**:
   - configured `blocked_instruments` set (FIGI) in `RiskLimits` — membership
     rejects;
   - optional broker-neutral `instrument_status_check` dependency
     (`callable(figi) -> bool | None`): `False` rejects, `None` (unknown) does
     not block, `True` passes.
5. **Configured position limit** — worst-case projected position vs
   `max_position_size` (pre-existing).
6. **Configured daily loss limit** — (pre-existing).

The bot RUNNING state is **not** checked inside RiskManager: the bot lifecycle
(MVP-6.5) remains the upstream lifecycle gate; no duplication. Verified by
`test_bot_lifecycle_gate_is_not_duplicated_in_risk_manager`.

## Broker-neutral dependency added

- `RiskManager(instrument_status_check: Callable[[str], bool | None] | None)` —
  a broker-neutral instrument trading-status provider. Defined and tested;
  production wiring is **not** done (see boundaries below). RiskManager still
  imports no broker code.

## Exact configuration source (added)

Minimal typed boundary in `app/core/config.py` (`Settings`, pydantic-settings,
environment variables), separate from strategy parameters:

- `risk_max_position_size: float | None`
- `risk_daily_loss_limit: float | None`
- `risk_max_concurrent_bots: int | None`
- `risk_blocked_instruments: list[str]`

`risk_limits_from_settings()` (app/trading/live_execution.py) maps only
explicitly configured values into `RiskLimits`; unset values leave the check
disabled. No financial defaults invented. `build_live_service()` now passes the
configured limits to the production `RiskManager`.

## Explicit unavailable boundaries (not fabricated)

- **Instrument trading-session status:** the `instrument_status_check`
  dependency is defined/tested but NOT wired in production. Instrument status
  lives in PostgreSQL behind the async `InstrumentService`; the execution gate
  is synchronous. Wiring requires an async-aware lookup (follow-up task). No
  hardcoded MOEX session rules.
- **Funds/position capacity:** broker account facts (`available_cash`,
  `equity`) are exposed only through async `BrokerAdapter` calls; the
  synchronous gate cannot consume them. The check is explicitly unavailable;
  no fake account balances or capacity values are used (verified by
  `test_no_fake_funds_or_capacity_data_used`).

## Tests

`backend/tests/test_risk_preconditions.py` — 16 focused test cases:

1. zero quantity rejected
2. negative quantity rejected
3. invalid LIMIT price rejected (None / 0 / negative — parametrized, 3 cases)
4. MARKET intent does not require a limit price
5. emergency stop rejects
6. configured position limit rejects
7. configured daily loss limit rejects
8. allowed order passes
9. configured instrument restriction rejects (`blocked_instruments`)
10. instrument status provider rejects when not permitted (unknown `None` passes)
11. no fake funds/capacity data is used (typed schema + behavior)
12. RiskManager remains broker-neutral (no T-Invest imports)
13. risk config mapping: only configured values applied
14. bot lifecycle gate not duplicated in RiskManager

Existing BotRuntime lifecycle tests (tests/test_bot_lifecycle.py) remain green
as part of the full run.

**Result: `pytest tests` → 311 passed, 1 skipped** (was 295 passed before this
change).

## Lint / build

- `ruff check app tests scripts` → **All checks passed!**
- `npm run build` (frontend) → **✓ built in 8.12s**

## Git

- Implementation commit: `3231a51384f968fb6b1c138cf939bacf21b4c81b`
  ("feat: complete MVP-6.6 risk manager execution preconditions") on local `master`.
- Published on `agent/review/mvp-6.6` (branch created at `3231a51`).
- `origin/master` NOT pushed; no merge/rebase performed.
