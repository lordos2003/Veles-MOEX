# Veles-MOEX — Independent Review: MVP-6.12

## Verdict (round 1)

**REJECTED — two corrections required (B1, B2) plus one owner-approved contract (D7)**

Reviewed implementation: `a4f792d39f12f2db7b88ce64ae3ed766e9200660` (`agent/review/mvp-6.12`, pushed, in sync with origin)
Base: `master @ 59a38974cd27405f40332806fee7dfa8fabc569e` (merge-base verified)
Report: `.agent/REPORT-MVP-6.12.md` (`agent/control @ ede6511`)
Reviewer: Claude (independent review), 2026-09-30

## Independent re-run (clean environment, Python 3.12, `pip install -e ".[dev]"`)

| Check | Result |
|---|---|
| `pytest` (full) | **433 passed, 1 skipped** — matches the REPORT |
| `ruff check app tests scripts` | All checks passed |
| `alembic heads` | single head `0005_deal_continuation` |
| push rule | review branch and REPORT pushed; the REPORT cites the pushed SHA ✓ |

## Blocking findings

### B1. A deal can be left without a take-profit: the old TP is cancelled before the new one passes the Risk Manager, and non-`DealError` failures escape the pump

`DealManager._rearm_tp()` first **cancels** the working TP, then builds the new one and calls `RiskManager.check_order()`. If the risk check rejects the new TP, the position is left with **no TP at all**. `RiskRejected` is not a `DealError`, so `pump()`:

- does not mark the Deal ERROR and does not block the bot;
- loses the remaining events of the batch (`events, self._pending = self._pending, []` is taken before the loop);
- propagates the exception out of the stream's `on_event` hook. The stream session fails, reconnects and re-runs recovery, which retries the same rejected TP in a loop.

The Risk Manager rejects TPs in realistic configurations, because both limits treat a position-**reducing** order as risk-increasing:

- `_check_position_size`: `projected = current + abs(intent.quantity)`, ignoring the side. A TP for the whole position projects `2 × position`.
- `_check_daily_loss`: once the limit is reached, **every** order is rejected, exits included.

Reproduced on `a4f792d` with the MVP-6.12 test harness (SIMPLE, 2 levels × 200 units, TP 10%):

| Probe | Result |
|---|---|
| P1: `max_position_size=300`, entry fill 200 | `RiskRejected: max position size exceeded: 400 > 300`; **0 working TPs**, deal `OPEN`, bot not blocked, exception escapes `pump()` |
| P2: TP working, then daily loss limit reached, DCA fill 200 | old TP **cancelled**, new TP `RiskRejected`; **position 400, 0 working TPs**, exception escapes `pump()` |

**Required correction**

1. **D7 (new contract, owner decision 2026-09-30, see the task):** position-reducing orders are exempt from `max_position_size` and `daily_loss_limit`. Emergency stop, quantity, price and instrument-permission checks still apply.
2. `_rearm_tp()`: compute the new TP and run `check_order()` **before** cancelling the old TP. If the new TP cannot pass (or cannot be computed), **keep the old TP working** and put the Deal/bot into ERROR (B2).
3. `pump()`: handle **every** exception per event. Mark that Deal ERROR, record the error, block the bot (B2), and **continue** with the remaining events. Never lose queued events, and never let a deal reaction raise out of the stream hook.
4. Tests: P1 and P2 as regressions (with D7 the TP is placed; with a rejection that D7 does not exempt, e.g. instrument blocked, the old TP stays working and the bot is ERROR); a mixed batch where one event fails and the others are still applied.

### B2. Deal errors are not surfaced: the bot stays RUNNING

On a deal failure the `DealManager` sets `deal.status = ERROR` and adds the bot to its internal `_blocked` set. Nothing else happens:

- the bot lifecycle state stays `RUNNING` (in the runtime and in the DB);
- `last_error` is read only by recovery;
- the API shows nothing.

Spec §12 and D4/D5 require the bot to **enter ERROR** and the error to be **explicit**.

The live cycle also silently ignores an OPEN position that has **no owning Deal** (`test_d6_open_live_cycle_creates_no_exit_intents_without_deal` asserts that nothing happens). At runtime this is a position without a TP, e.g. after a deal failure or a position opened outside the bot. This is the D5 contradiction and must not be silent.

**Required correction**

1. A deal failure (from `pump()`, `open_deal()` or recovery) transitions the bot to **ERROR** through the existing bot lifecycle (`BotRuntimeManager`), persisted via `BotRepository`, with the existing ERROR semantics (execution blocked until an explicit START).
2. The reason is observable: expose the last deal error in `GET /api/bots/{id}` (read-only field, e.g. `deal_error`).
3. A live cycle that finds the position OPEN (reconciled, sign matching) **without** an owning non-CLOSED Deal puts the bot into ERROR with an explicit reason. Replace `test_d6_open_live_cycle_creates_no_exit_intents_without_deal` accordingly.
4. A new START after ERROR follows the existing lifecycle. A blocked deal must be reconciled (D5) before a new Deal opens.

## Accepted in round 1 (no change requested)

- **D1**: `validate_live_deal_config()` covers all excluded modes; rejection at the engine factory (START) → 409.
- **D2**: the full grid is built once from the snapshot price; C3 and D3 apply to **every** level; the Deal is persisted before the first submission; deterministic intent ids; `active_limit` promotion keeps the working count; partial TP fills keep the TP working; a zero position cancels the remaining grid orders → CLOSED → next FLAT entry with the current deposit.
- **D3**: safe-direction tick rounding in `Decimal`; a missing tick blocks the whole entry.
- **D4** (apart from B1): TP from the PositionManager **average**, whole position, lot- and tick-rounded; never two working TPs in the tested paths. The cancel path uses `OrderManager.cancel()`, which is synchronous against the broker, and UNKNOWN → reconciliation.
- **D5** (apart from B2): recovery keeps working orders, applies broker fills, places a missing TP only after a successful reconciliation, and stops on unknown or contradicting facts.
- **D6**: the live OPEN cycle no longer builds exits from the market price. The removed tests (`test_mvp611`: 6 OPEN exit tests; `test_mvp69`: 2 engine exit tests; the `test_mvp610` position-invariant assertion) cover exactly the behaviour D6 removes.
- Clean-up of `make_deposit_provider()` done. Broker neutrality holds (no `app.brokers.tinvest*` import in the deal layer).

## Observations (non-blocking)

1. **Recovery re-arms the TP on every restart** once any level is FILLED (`rearm = True` also for fills already reflected in the working TP). This causes needless cancel/replace churn. Prefer re-arming only when the filled quantity differs from what the Deal recorded at its last TP.
2. With D6 the B1/C6 regressions from MVP-6.11 (an open position unaffected by deposit edits or clearing) were removed together with the old exit path. Add one Deal-level regression: deposit cleared or edited while a Deal is OPEN → the TP re-arm on the next grid fill is unchanged (the Deal uses the captured deposit, and the re-arm never reads it).

## Acceptance conditions (round 2)

1. D7 implemented in `RiskManager` with tests (reducing vs increasing orders, both limits, emergency stop still blocking).
2. B1 and B2 corrected as described, with the listed regressions.
3. Full `pytest`, `ruff`, `alembic heads`, `npm run build`.
4. Commit pushed to `agent/review/mvp-6.12`; `.agent/REPORT-MVP-6.12-REV1.md` committed and pushed to `agent/control`, citing the pushed SHA.
5. `master` unchanged.

**No publication to master.**
