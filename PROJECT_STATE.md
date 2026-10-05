# Veles-MOEX — Project State

## Project
- Repository: `lordos2003/Veles-MOEX`
- Goal: Veles-like web trading application for MOEX using T-Invest as the initial broker integration.
- Initial broker boundary: no direct MOEX API. `TInvestAdapter.place_order()` (PostOrder, MVP-6.2) exists behind `RiskManager -> OrderManager`, but no live strategy cycle is scheduled/enabled in production yet (see Known boundaries).

## Canonical workflow
`agent/control -> agent/review/mvp-X -> independent review (ChatGPT / Claude) -> master`

- `agent/control` is the canonical control/audit source.
- New tasks, audits and reviews start from the current `agent/control`.
- Кодер implements only on the assigned `agent/review/mvp-X` branch.
- Кодер must not publish to `master`.
- Only independently accepted work is published to `master`.
- `PROJECT_STATE.md`, current task, review and reports are maintained on `agent/control`; accepted records are mirrored to `master` for repository recovery.

## Current task

### MVP-7.1 — Экраны: стратегии (полная форма), боты, сделка, бэктест, песочница
**Status: CHANGES REQUESTED (раунд 1, 2026-10-05)** — `7d662be`; см. `.agent/REVIEW-MVP-7.1.md` (B1 стратегии/счета не сохраняются в PostgreSQL, B2 миграция 0002 не проходит на чистой базе — обе ошибки уже в `master`; B3–B7 интерфейс).

- Задание: `.agent/TASK-MVP-7.1-UI.md`
- Ветка: `agent/review/mvp-7.1` (от `master` @ `795f4ed`)
- Контракт U1–U8 (владелец, 2026-10-05): разделы на русском с терминами Veles; индикатор режима и подтверждение старта на боевом счёте (`GET /api/runtime`); каталог индикаторов из реального расчёта (`GET /api/strategies/indicators`, без значений по умолчанию); полная форма стратегии по JSON Schema с версиями и JSON-видом; боты и страница сделки; бэктест с графиком; песочница и счета; vitest. Интерфейс не придумывает значений.
- При первом запуске в песочнице проверить вручную: события `OrderStateStream`; поведение сделки, когда песочница удаляет неисполненные заявки после сессии.
- Остальные кандидаты: мульти-тейк / безубыток / сигнальный TP / сигнальный стоп / подтяжка / режим «Сигнал» в живой торговле; кэш свечей для M1; время свечей `HOUR_4`/`WEEK_1`/`MONTH_1`; перевыставление TP при перезапуске; ошибка `FILLED -> UNKNOWN`; политика единичного сбоя чтения `GetStopOrders`.

## Current accepted MVP

### MVP-7.0 — Удобный локальный запуск, песочница и API для стратегий, ботов и бэктеста
**Status: ACCEPTED (раунд 2, 2026-10-05) and published to master.**

- Принятая реализация: `76cba1e`
- Publication PR: #18
- Publication merge commit: `0723e87c3f62c6f4c092c260f755ae49e062a60b`
- Задание: `.agent/TASK-MVP-7.0-LOCAL-RUN-AND-API.md`; ревью: `.agent/REVIEW-MVP-7.0.md`; отчёты: `.agent/REPORT-MVP-7.0.md`, `.agent/REPORT-MVP-7.0-REV1.md`
- Контракт R1–R8 (владелец, 2026-10-05): `docker compose up` с корневым `.env` и автомиграциями, порты только `127.0.0.1`; синхронизация счетов; песочница (открыть/пополнить/закрыть; стоп-заявок нет → START бота со SL в песочнице 409); стратегии с неизменяемыми версиями, JSON Schema, validate; боты (создание, смена версии и удаление только STOPPED без незакрытой сделки); просмотр сделок; бэктест по API (капитал = депозит, предел свечей до запросов, таймфрейм = таймфрейм стратегии); объём бэктеста от депозита по C1–C3.
- Проверка (независимо): `pytest 560 passed, 1 skipped`; `ruff` чисто.

### MVP-6.16 — Простой стоп-лосс в живой торговле
**Status: ACCEPTED (раунд 2, 2026-10-05) and published to master.**

- Принятая реализация: `a3e59e6`
- Publication PR: #16
- Publication merge commit: `fdbc4e6a6752ae0c0ba49b01b532d01e502be805`
- Задание: `.agent/TASK-MVP-6.16-STOP-LOSS.md`; ревью: `.agent/REVIEW-MVP-6.16.md`; отчёты: `.agent/REPORT-MVP-6.16.md`, `.agent/REPORT-MVP-6.16-REV1.md`
- Контракт E1–E5 (владелец, 2026-10-02): уровень = P0 × (1 ∓ (перекрытие + SL)%), округление к более раннему срабатыванию, активен после исполнения всей сетки; стоп-заявка T-Invest (STOP_LOSS по рынку, до отмены) на всю позицию с перевыставлением через Risk; `GetStopOrders` со `STOP_ORDER_STATUS_ALL` в окне сделки; `close_reason` (миграция `0006_stop_loss`); `stop_bot_after` задаётся явно (None → 409); бэктест на той же формуле.
- Проверка (независимо): `pytest 543 passed, 1 skipped`; `ruff` чисто.

### MVP-6.15 — Снимок рынка по числу баров с учётом перерывов в торгах
**Status: ACCEPTED (раунд 1, 2026-10-02) and published to master.**

- Принятая реализация: `941e267`
- Publication PR: #14
- Publication merge commit: `143f2a40befca22e0cd1d200406d66a9ba311db7`
- Задание: `.agent/TASK-MVP-6.15-SNAPSHOT-BY-BAR-COUNT.md`; ревью: `.agent/REVIEW-MVP-6.15.md`; отчёт: `.agent/REPORT-MVP-6.15.md`
- Контракт L1–L4 (владелец, 2026-10-02): снимок = `lookback_bars` последних существующих свечей; добор назад до `max(14 дней, 4 × lookback × ТФ)`; при нехватке истории — сколько есть; `NoTradesInWindow` только если пусто на всей глубине. Заменяет «окно по часам» MVP-6.10.
- Проверка (независимо): `pytest 508 passed, 1 skipped`; `ruff` чисто.


### MVP-6.14 — No-Trade Bars Are Skipped, Not Failures
**Status: ACCEPTED (round 1, 2026-10-01) and published to master.**

- Accepted implementation: `c1558bd`
- Publication PR: #12
- Publication merge commit: `d1ac72e68d4163fa56652c20de89558f4da1f5a6`
- Control task: `.agent/TASK-MVP-6.14-NO-TRADE-BAR.md`; review: `.agent/REVIEW-MVP-6.14.md`; report: `.agent/REPORT-MVP-6.14.md`
- Contract N1–N3 (owner, 2026-10-01): a proven no-trade bar (no candle in the bar, and a newer candle exists or the last-trade time is before the bar) is an uncounted skip (no cycle; `last_skip_reason` in the API); unproven → MVP-6.13 behaviour (a lagging feed is still detected). `MarketSnapshot.last_trade_at`, `NoTradesInWindow`.
- Validation (independent, clean env): `pytest 499 passed, 1 skipped`; `ruff` clean.


### MVP-6.13 — Live Cycle Scheduler
**Status: ACCEPTED (round 5, 2026-10-01) and published to master.**

- Accepted implementation: `db09a39`
- Publication PR: #10
- Publication merge commit: `0279507e06db5403f063b66072298e8c1dd3d2cd`
- Control task: `.agent/TASK-MVP-6.13-LIVE-CYCLE-SCHEDULER.md`; review: `.agent/REVIEW-MVP-6.13.md` (rounds 1–4 REJECTED: B1–B6; round 5 ACCEPT); reports: `REPORT-MVP-6.13.md`, `-REV1` … `-REV4`
- Contracts S1–S6 (owner-approved 2026-09-30): per-bot ticks by Veles calculation method (`AT_BAR_CLOSE` +5 s with closed-bar confirmation / `PER_MINUTE`), started only after a SAFE recovery; broker trading-status gate (`GetTradingStatus`); one transient failure per tick, 3 consecutive ticks → bot ERROR, non-transient → ERROR immediately; S6 deferred bar-close tick outside the session (bounded, 5-s status polling).
- Live-session DB access serialised behind one `asyncio.Lock` (verified on PostgreSQL 16 + asyncpg).
- Validation (independent, clean env): `pytest 486 passed, 1 skipped`; `ruff` clean; alembic head `0005_deal_continuation`.

Known boundaries: (no-trade bars resolved by MVP-6.14); wall-clock snapshot window (MVP-6.10) after session gaps; `HOUR_4`/`WEEK_1`/`MONTH_1` candle start times unverified; only Simple TP; one bot per instrument.


### MVP-6.12 — Live Deal Continuation (Simple TP, Simple/Custom grid)
**Status: ACCEPTED (round 3, 2026-09-30) and published to master.**

- Accepted implementation: `418c24e`
- Publication PR: #8
- Publication merge commit: `566d79277e3667ea80e3cccba148158248fafd83`
- Control task: `.agent/TASK-MVP-6.12-DEAL-CONTINUATION.md`; review: `.agent/REVIEW-MVP-6.12.md` (round 1 REJECTED B1/B2, round 2 REJECTED B3, round 3 ACCEPT); reports: `REPORT-MVP-6.12.md`, `-REV1.md`, `-REV2.md`
- Contracts D1–D7 (owner-approved 2026-09-30): live deals only for SIMPLE/CUSTOM + Simple TP (others rejected at START); event-driven Deal lifecycle; safe-direction tick rounding; TP from the PositionManager average re-armed on every grid fill (never two TPs, never larger than the position); durable Deal (`0005_deal_continuation`) + recovery; no exits from the live cycle; reducing orders exempt from position-size / daily-loss limits.
- Deal failures move the bot to ERROR (persisted; `deal_error` in `GET /api/bots/{id}`); an OPEN position without an owning Deal errors the bot.
- Validation (independent, clean env): `pytest 450 passed, 1 skipped`; `ruff` clean; alembic head `0005_deal_continuation`.

Known boundaries: no live cycle scheduler (superseded by MVP-6.13, in review); only Simple TP; position state per FIGI (one bot per instrument); Backtest sizing differs from the Live deposit contract.


### MVP-6.11 — Bot Deposit Sizing & Entry from Confirmed Flat
**Status: ACCEPTED (round 3, 2026-09-30) and published to master.** (Deal-related boundaries superseded by MVP-6.12.)

- Accepted implementation: `e026886dfdc6f98112dfc214060c5fc2bb2ae075`
- Publication PR: #6
- Publication merge commit: `40cf6ce802e685b99ae527758949e29a8a67d26d`
- Control task: `.agent/TASK-MVP-6.11-BOT-DEPOSIT-SIZING.md`
- Control review: `.agent/REVIEW-MVP-6.11.md` (round 1 REJECTED B1, round 2 REJECTED B2, round 3 ACCEPT)
- Reports: `.agent/REPORT-MVP-6.11.md`, `.agent/REPORT-MVP-6.11-REV1.md`, `.agent/REPORT-MVP-6.11-REV2.md`

Contracts (owner-approved 2026-09-29/30):
- C1/C5 `Bot.deposit` (bot setting, migration `0004_bot_deposit`, `GET/PATCH /api/bots/{id}`, `> 0`, `deposit` key required on PATCH);
- C2 sum of all grid-order nominals of a deal = deposit (SIMPLE `D/Σkⁱ`, CUSTOM `D×pct/100` with the >100% guard, SIGNAL blocked — no order limit invented); spot 1:1, no leverage;
- C3 MOEX lots rounded down; any level below one lot blocks the whole entry; missing lot/currency blocks;
- C4 live position state UNKNOWN / FLAT / OPEN / SIGN_MISMATCH, established only by a successful broker reconciliation; FLAT → entry only (no active bot orders); OPEN → exits only; others → nothing;
- C6 deposit edits apply from the next deal: fresh DB read (`populate_existing`) at each FLAT entry; an open deal is unaffected;
- C7 market snapshot trimmed to exactly `lookback_bars` (Issue #3);
- B1 exits of an open position never depend on entry sizing.

Validation (independent, clean env): `pytest 412 passed, 1 skipped`; `ruff check app tests scripts` passed; alembic single head `0004_bot_deposit`; `npm run build` passed (no frontend changes).

Known boundaries:
- no live cycle scheduler; the strategy cycle is triggered explicitly;
- no deal continuation: while OPEN only exits are produced; averaging after entry is not implemented;
- TP price is derived from the market-context price, not the average entry price (pre-existing);
- position state is per FIGI, not per bot (manual trades / several bots on one instrument share it);
- Backtest sizing (`BacktestConfig.quantity`) differs from the Live deposit contract C2;
- SIGNAL-mode live entry is blocked until an order-limit contract is approved.

### MVP-6.10 — Live Market Snapshot & Per-Bot Timeframe
**Status: ACCEPTED and published to master.**

- Accepted implementation: `c7429fdee1792962a679f1924230d99c62573efc`
- Publication PR: #4
- Publication merge commit: `14168ca798c00b8a28ef278bb245391a07bce958`
- Control task: `.agent/TASK-MVP-6.10-MARKET-SNAPSHOT.md`
- Control review: `.agent/REVIEW-MVP-6.10.md`
- Control report: `.agent/REPORT-MVP-6.10.md`

Round-2 corrections:
- removed inferred indicator warmup / `required_bars` semantics;
- introduced explicit `StrategyConfig.lookback_bars`;
- **correction (2026-09-30):** the exact `lookback_bars` trim was not in the MVP-6.10 code; delivered by MVP-6.11 C7 (PR #6, Issue #3 closed);
- MVP-6.9 position-state invariant remains intact.

Validation recorded for MVP-6.10: `pytest 369 passed, 1 skipped`; `ruff check app tests scripts` passed; `npm run build` passed.

Known boundaries:
- T-Invest order placement exists at adapter level (`TInvestAdapter.place_order`, MVP-6.2) behind Risk/Order Manager; production live trading is not enabled (no scheduled live cycle, no deal continuation);
- live cycle scheduling is outside MVP-6.10;
- multi-timeframe filter series require a separately specified implementation;
- authoritative production sizing remains governed by the accepted PositionManager boundary.

### MVP-6.9 — Position State & Authoritative Quantity
**Status: ACCEPTED and published.**
- Accepted review commit: `5b4c42be4d49d700e8750315c1da81b17bc04a1d`
- Publication PR: #2
- Publication merge commit: `cdc10296e32509f2d716c85c1b58e62a9b01b2cf`
- PositionManager is the authoritative live execution quantity source.
- Unresolved position state blocks all live ExecutionIntent creation/submission.

## Architecture
- Broker integration is behind `BrokerAdapter`.
- `TInvestAdapter` uses the official REST API: read access plus `PostOrder`-based `place_order` (MVP-6.2) behind the Risk/Order Manager.
- Domain prices/monetary values use `Decimal`.
- Market timestamps are timezone-aware UTC.
- Instrument identity uses FIGI.
- `MarketCandle` uniqueness: `(figi, timeframe, timestamp)`.
- Veles Filter/Signal semantics: Argument1 + Operator + Argument2; AND within group, OR between groups; state operators `>`/`<`, event operators for crossings.
- DCA/Grid and Backtest semantics are preserved across live-market-data work.

## Workflow rule: push before review
Work is delivered only when `agent/review/mvp-X` and the REPORT on `agent/control` are pushed to GitHub (plain push, no `--force`/rebase). See `.agent/CODER-WORKFLOW.md` → "Mandatory push rule". The same rule is in `AGENTS.md` §6 (published with MVP-6.11).

## Recovery
For a new ChatGPT/Кодер session:
1. Start from `agent/control`.
2. Read `PROJECT_STATE.md`.
3. Read the current `.agent/TASK-*.md`, applicable `.agent/REVIEW-*.md`, and latest `.agent/REPORT-*.md`.
4. Check current Git branch/HEAD and compare with `master` when required.
5. Continue from the accepted MVP and current control task; do not reconstruct state from chat history.
