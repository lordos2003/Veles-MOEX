# MVP-6.9 — Position State & Authoritative Quantity

## Branches and workflow

- Task is recorded on `agent/control`.
- Implementation branch: `agent/review/mvp-6.9`.
- Base: `master @ b2c4ee27cdd1bcf67bb69c2f22374cb062bebb52`.
- Do not modify `master`.
- After implementation, report results to `agent/control`.
- Wait for independent ChatGPT review before any publication to `master`.

## Objective

Eliminate the remaining live-execution quantity boundary from MVP-6.8.

MVP-6.8 deliberately left `position_qty=1.0` in the ExitPlan path because there was no authoritative live position source. MVP-6.9 must introduce a broker-neutral PositionManager and make the real position quantity the only authoritative quantity source for live execution.

## Required implementation

1. Introduce a broker-neutral `PositionManager`.
2. Obtain the current position by FIGI through the broker-neutral adapter layer and the existing T-Invest read-only integration.
3. Normalize FIGI, side, quantity, average price, and position state / presence.
4. Introduce explicit domain handling for unavailable/invalid positions, e.g. `PositionUnavailable` and `InvalidPositionQuantity`.
5. PositionManager must be the only authoritative source of quantity for live execution.
6. Remove `position_qty=1.0` from the live execution path.
7. Pass real quantity through PositionManager -> Exit/Strategy planning -> ExitPlan -> ExecutionIntent -> RiskManager -> OrderManager.
8. No position: no live order.
9. Quantity <= 0: no live order.
10. Sign-inconsistent position: no live order.
11. No fabricated or default fallback quantity.
12. Preserve existing DCA/Grid mathematics.
13. Preserve Backtest semantics.
14. Keep T-Invest read-only. Do not implement actual live order submission.
15. Do not implement Multi-Take, Signal TP, Minimum P&L, Break-Even, Stop Loss, Trailing, Paper Trading, optimizer, UI, Veles Filter/Signal changes, or DCA/Grid redesign.

## Architectural constraints

Do not bypass PositionManager by reading positions directly from BrokerAdapter inside StrategyEngine, ExitEngine, BotRuntime, or OrderManager.

The authoritative path is:

T-Invest
-> BrokerAdapter
-> PositionManager
-> real position quantity
-> Exit/Execution planning
-> ExecutionIntent
-> RiskManager
-> OrderManager

Broker DTOs must not leak into strategy/domain logic.

## Tests

Add focused tests covering at least:

1. valid real position;
2. missing position;
3. quantity == 0;
4. negative/sign-mismatched quantity;
5. real quantity reaches ExitPlan;
6. real quantity reaches ExecutionIntent;
7. no live order when position is absent;
8. no live order for zero quantity;
9. no live order for sign-mismatched quantity;
10. no fallback quantity;
11. existing Backtest behavior remains unchanged;
12. existing DCA/Grid behavior remains unchanged.

For the negative cases, assert the complete live order path is empty (for example `OrderManager.list_orders() == []`), not merely that no SELL exit order exists.

Also run:

- `pytest`
- `ruff check app tests scripts`
- `npm run build`

## Review finding — BLOCKER

Independent ChatGPT review of implementation commit `5acc7a79d1159b134b9a3a6e0c0a3b9c114404be` found a live orchestration defect:

`TradingEngine.process()` maps `PositionUnavailable` / `InvalidPositionQuantity` to `position_qty=None`, but `StrategyEngine.evaluate()` can still build DCA/Grid orders from the configured `base_nominal`. `plan_to_intents()` then converts those Grid orders into live `ExecutionIntent` objects.

Therefore the current implementation can produce a live Grid order even when no valid position quantity exists. This violates the MVP-6.9 requirement: no position / invalid quantity => NO LIVE ORDER.

Required correction:

- At the live orchestration boundary, missing/invalid position state must prevent creation/submission of **all** live ExecutionIntents for that processing cycle.
- Do not change DCA/Grid mathematics.
- Do not change Backtest semantics.
- Add regression tests proving `OrderManager.list_orders() == []` for absent, zero, and sign-mismatched positions.
- Re-run full validation.
- Commit only on `agent/review/mvp-6.9`.
- Update `.agent/REPORT-MVP-6.9.md` in `agent/control`.
- Do not modify `master`.
- Stop for a new independent ChatGPT review.

## Completion protocol

1. Implement only MVP-6.9 and the review correction above.
2. Commit implementation on `agent/review/mvp-6.9`.
3. Do not merge or push to `master`.
4. Update `agent/control` with the implementation report, including commit SHA, changed files, architecture decisions, validation results, and known limitations.
5. Explicitly confirm that no fabricated/default live quantity remains and that invalid/missing position state cannot produce any live ExecutionIntent.
6. Stop and wait for ChatGPT review and acceptance.
