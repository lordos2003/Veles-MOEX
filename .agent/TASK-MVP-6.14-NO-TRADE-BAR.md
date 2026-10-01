# TASK-MVP-6.14 — No-Trade Bars Are Skipped, Not Failures

## Status

**ACCEPTED (round 1, 2026-10-01)** — accepted implementation `c1558bd`; awaiting publication to `master`

Control branch: `agent/control`
Implementation branch: `agent/review/mvp-6.14` (create from current `master` @ `bb52d36`)
Base: `master` @ `bb52d368c82ae5e32ff8fa3cae41ba5439191321` (contains accepted MVP-6.13, merge `0279507`)
Date: 2026-10-01

## Why this MVP

On MOEX/T-Invest a bar interval without trades has **no candle** (the broker returns no empty candles). The MVP-6.13 scheduler treats a missing closed bar as "not confirmed". After `max_wait` it counts **one transient failure**, and 3 consecutive ticks → bot ERROR. A bot on a thin instrument (M1/M5) is therefore put into ERROR during an ordinary quiet period, although nothing is broken (MVP-6.13 review rounds 2–5, open owner item).

A related case: if no trades happened during the whole snapshot window, `MarketDataService.get_snapshot()` raises `MarketDataUnavailable("no candle history")`, which is also counted.

## Approved contract (project owner, 2026-10-01)

### N1. A proven no-trade bar is a skipped tick: not counted, no cycle

When the broker answered normally but the bar had no trades, there is no new information. The tick is **skipped**: no strategy cycle, no failure count, and the consecutive-failure counter is **not reset** (a skip is neither a success nor a failure). The reason is observable via a read-only `last_skip_reason` in `GET /api/bots/{id}`.

"No trades in the bar" must be **proven** from broker facts. Otherwise the existing MVP-6.13 behaviour applies (wait until `max_wait`, then one transient failure), because a lagging data feed must still be detected.

A target bar `[bar_start, boundary)` counts as **proven no-trade** when the snapshot request succeeded and:

- (a) the snapshot has no candle in `[bar_start, boundary)`, **and**
- (b) either a candle with `start ≥ boundary` exists (the broker's data is already past the target bar), **or** the broker's **last-trade time** is known and `< bar_start` (no trade since before the bar began).

An empty window counts as proven no-trade when the last-trade time is known and earlier than the window start. If the last-trade time is unknown (`None`), nothing is proven.

### N2. Broker facts needed (no inference)

- `MarketSnapshot` gains `last_trade_at: datetime | None`, the broker's last-trade timestamp (`LastPrice.timestamp`), `None` when the broker gave none. It is a separate field: the existing `timestamp` field keeps its MVP-6.10 meaning and fallback.
- `MarketDataService.get_snapshot()` keeps raising `MarketDataUnavailable` for an empty window, but raises a **subclass** `NoTradesInWindow(MarketDataUnavailable)` carrying `last_trade_at` and `window_start` when the last price is usable and the window has no candles. All existing `MarketDataUnavailable` handling keeps working unchanged.
- Document in §32 that `LastPrice.timestamp` is used as "last trade time" (T-Invest `GetLastPrices.time`), with the source.

### N3. Where it applies

- `AT_BAR_CLOSE`, normal path: N1 is checked on each confirmation attempt. A proven no-trade bar concludes the tick as a skip at once (no need to wait for `max_wait`).
- `AT_BAR_CLOSE`, deferred path (S6): unchanged semantics. A proven no-trade bar while deferred is "not confirmed yet"; the S6/B4 rules decide.
- `PER_MINUTE`: a `NoTradesInWindow` whose `last_trade_at < window_start` → skip, not counted. The forming bar without any candle is not a failure.
- Nothing else changes: S1–S6, the B1–B6 rules, the failure threshold, and the Deal / Risk / strategy semantics.

## Scope

1. `MarketSnapshot.last_trade_at`, `NoTradesInWindow` (N2).
2. Scheduler N1/N3 + `last_skip_reason` (scheduler-held, per bot, in memory) exposed read-only in `GET /api/bots/{id}`.
3. Docs: `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md §32 MVP-6.14`.

## Tests (focused, `backend/tests/test_mvp614_no_trade_bar.py`, fake clock)

1. M5: no candle in the target bar, a candle `start ≥ boundary` exists → skip, 0 failures, no cycle, `last_skip_reason` set.
2. M5: no candle in the target bar, `last_trade_at < bar_start`, no newer candle → skip, 0 failures.
3. M5: no candle in the target bar, `last_trade_at` unknown and no newer candle → **not proven** → MVP-6.13 behaviour (one failure at `max_wait`).
4. M5: no candle, `last_trade_at ≥ bar_start` (trades happened, data lagging) → not proven → one failure at `max_wait`.
5. 10 consecutive proven no-trade bars → bot stays RUNNING; the counter neither increases nor resets (2 earlier failures + skips + 1 failure → ERROR).
6. Empty window: `NoTradesInWindow` with `last_trade_at < window_start` → skip (`AT_BAR_CLOSE` and `PER_MINUTE`); with `last_trade_at` unknown → counted as before.
7. Deferred (S6) path unchanged: the existing MVP-6.13 S6/B4/B5/B6 tests stay green.
8. `get_snapshot`: empty window + usable last price → `NoTradesInWindow` (a subclass of `MarketDataUnavailable`) with the fields; `last_trade_at` is filled from `LastPrice.timestamp`.
9. Full suite green.

## Explicit constraints (AGENTS.md)

- No inferred trading semantics. "No trades" only from the facts in N1/N2; otherwise unchanged behaviour.
- Broker neutrality; `Decimal` / UTC unchanged; no change to the snapshot trimming (C7) or the lookback contract.
- Out of scope: snapshot by bar count across session gaps (separate MVP), exit modes.

## Validation & REPORT

Full `pytest`, `ruff check app tests scripts`, `alembic heads` (unchanged), `npm run build`, diff review against the merge-base.

REPORT → `agent/control:.agent/REPORT-MVP-6.14.md` with: task, branch, **pushed** SHA ("pushed, in sync with origin"), exact changes, validation, known limitations, documentation gaps, AGENTS.md compliance.

Do not publish to `master`. Do not self-declare acceptance.

## Publication (mandatory, see `AGENTS.md` §6)

```
git push origin agent/review/mvp-6.14
git push origin agent/control
git ls-remote origin agent/review/mvp-6.14 agent/control
```

No `--force`, no rebase. If rejected: `git fetch origin`, `git merge origin/<branch>`, push again. Never push `master`.
