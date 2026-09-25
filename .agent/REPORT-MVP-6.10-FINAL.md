# REPORT — MVP-6.10 Live Market Snapshot & Per-Bot Timeframe (final control)

- Status: IMPLEMENTED, revision 2 (review corrections applied). НЕ объявляем accepted — приёмка только независимым ревью.
- Date: 2026-09-25
- Task: `.agent/TASK-MVP-6.10-MARKET-SNAPSHOT.md`
- Review: `.agent/REVIEW-MVP-6.10.md` (round 1, REJECTED — self-defined indicator warmup rules)
- Previous reports: `REPORT-MVP-6.10.md`, `REPORT-MVP-6.10-REV1.md`, `REPORT-MVP-6.10-REV2.md`

## 1. Branch / commits

| Item | SHA |
|---|---|
| Implementation branch | `agent/review/mvp-6.10` |
| Base (merge-base с master) | `cdc10296e32509f2d716c85c1b58e62a9b01b2cf` (master перед MVP-6.10, merge PR #2 / MVP-6.9) |
| Initial implementation | `4c4e8fa` |
| Review correction rev 1 (warmup map removed) | `27d469c` |
| **Final commit** | **`c7429fdee1792962a679f1924230d99c62573efc`** |
| origin/agent/review/mvp-6.10 | `c7429fdee1792962a679f1924230d99c62573efc` (published, in sync) |
| origin/master (unchanged) | `2280075e9309f3468d0e7529d5cc9e3d14363cc1` |

## 2. Что исправлено после review

### Round 1 (rev 1, `27d469c`)
- Удалён `_INDICATOR_WARMUP_BARS` — self-defined indicator warmup map больше нет в кодовой базе.

### Round 2 (rev 2, `c7429fd`, финальный)
По замечанию, что `period + shift + 1` и `+1` для crossing — тоже self-derived rules:

1. **Полностью удалены** `required_bars()`, `_argument_required_bars()`, `_groups_required_bars()` из `backend/app/strategies/config.py`. `git grep required_bars backend/` — ноль совпадений.
2. **Введён отдельный явно конфигурируемый параметр** `StrategyConfig.lookback_bars: int | None = Field(default=None, ge=1)` (`backend/app/strategies/config.py:219`). Это project-level contract parameter, а не Veles-семантика:
   - `None` (не задан) → live-цикл явно блокируется исключением `LookbackNotConfigured` (`backend/app/trading/market_context.py`), broker-запросы не выполняются;
   - неположительное значение → `StrategyLoadError` при загрузке стратегии (pydantic `ge=1`).
3. **Lookback в цикле live-стратегии берётся только из `StrategyConfig.lookback_bars`**: `build_market_snapshot_context()` (`backend/app/trading/market_context.py:129`) → `MarketDataService.get_snapshot(figi, timeframe, lookback_bars)` (явный параметр, без default). Никакой inference из period/shift/crossing, warmup, indicator semantics.
4. Ограничение зафиксировано в коде (docstrings `market_context.py`, `live_execution.py`, `config.py`), в `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` §28 и в отчётах.

## 3. Фактический diff против merge-base (проверен построчно)

`git diff cdc10296e32509f2d716c85c1b58e62a9b01b2cf..c7429fd` — ровно 11 файлов, +1198/−24:

| File | Изменение |
|---|---|
| `backend/app/domain/marketdata.py` | +27: `MarketSnapshot` (frozen dataclass: figi, timeframe, UTC timestamp, `Decimal` last_price, candles), `MarketDataUnavailable` |
| `backend/app/services/market_data.py` | +55: `_TIMEFRAME_SECONDS` (размер окна запроса), `MarketDataService.get_snapshot(figi, timeframe, lookback_bars)` — только реальные broker-данные; нет цены/свечей → `MarketDataUnavailable` |
| `backend/app/strategies/config.py` | +16: `StrategyConfig.timeframe: Timeframe \| None`, `StrategyConfig.lookback_bars: int \| None (ge=1)` |
| `backend/app/trading/market_context.py` | +117/−6: `TimeframeNotConfigured`, `LookbackNotConfigured`, `market_snapshot_to_context()`, `build_market_snapshot_context()`; MVP-6.8 `build_market_context` сохранён |
| `backend/app/trading/engine.py` | +48: `_require_live_timeframe()`, `_snapshot_gates_execution()`; гаты в `process()` после position gate (MVP-6.9) |
| `backend/app/trading/bot_lifecycle.py` | +43/−7: `BotRuntime.market_context_provider`, `execute_strategy(context=None)` — None → provider, иначе явный fail |
| `backend/app/trading/live_execution.py` | +62/−7: `_make_market_context` provider в `build_live_service`; контракт задокументирован в docstring |
| `backend/app/trading/__init__.py` | exports: `LookbackNotConfigured`, `TimeframeNotConfigured`, `build_market_snapshot_context`, `market_snapshot_to_context` |
| `backend/tests/test_mvp610_market_snapshot.py` | +731: 25 focused tests |
| `backend/tests/test_mvp69_position_state.py` | +3: `timeframe` в live-конфигах |
| `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` | +107: §28 MVP-6.10, explicit lookback contract |

### Проверки по пунктам контроля

1. **`required_bars()`** — удалена: `git grep -n "required_bars" c7429fd -- backend/` → 0 совпадений.
2. **`_INDICATOR_WARMUP_BARS`** — удалён: `git grep -n "_INDICATOR_WARMUP_BARS" c7429fd -- backend/` → 0 совпадений.
3. **Производные правила period/shift/crossing для lookback** — отсутствуют: в новом коде слова period/shift/cross/warmup встречаются только в docstring/комментариях, фиксирующих, что lookback НЕ выводится из indicator semantics (тест `test_lookback_is_not_inferred_from_indicator_period_or_shift` фиксирует это regression-поведением: конфиг с period/shift и без `lookback_bars` → `LookbackNotConfigured`).
4. **Lookback используется только явно заданный** `StrategyConfig.lookback_bars`: единственная точка передачи — `build_market_snapshot_context()` → `get_snapshot(figi, timeframe, lookback_bars)`; в service lookback — обязательный параметр без default; глобальных/implicit значений нет.

## 4. Валидация (выполнена на `agent/review/mvp-6.10` @ `c7429fd`)

| Check | Результат |
|---|---|
| pytest (backend) | **373 passed, 1 skipped** (2 warnings, 16s); focused: 25 тестов `test_mvp610_market_snapshot.py` |
| ruff check app tests scripts | **All checks passed** |
| npm run build (frontend) | **built in 10.71s** (dist/assets/index-hniSO0q7.js 152.28 kB) |
| diff review | полный diff против merge-base проверен построчно (11 файлов) |
| working tree | clean; master не изменён |

## 5. Соответствие AGENTS.md (master `2280075`)

- §1 Mandatory context recovery: выполнен — проверены branch/HEAD/master, TASK/REVIEW/REPORT, архитектура (TASK-09), Veles Help Center reference.
- §2 Veles compatibility HARD RULE: **соблюдено** — warmup/history/lookback/crossing semantics не изобретаются; документация Veles не определяет universal warmup/lookback rule, поэтому правило НЕ придумано, а зафиксирована явная граница: lookback — explicit project parameter, missing → блок цикла.
- §3 Documentation-first: источник поведения зафиксирован; неоднозначность сохранена, undocumented contract не создавался.
- §4 Branch discipline: реализация только в `agent/review/mvp-6.10`; master не тронут; force-push/rebase отсутствуют; MVP не объявлен accepted.
- §5 Scope discipline: не изменены Veles Filter/Signal semantics, DCA/Grid, Backtest, PositionManager quantity authority (MVP-6.9 gate сохранён), broker-neutral архитектура, Decimal, UTC, T-Invest read-only boundary.
- §6 Validation and reporting: тесты, ruff, npm build, diff — выполнены; отчёт содержит все требуемые пункты.

## 6. Подтверждение: Veles-specific semantics не изобретались

- Никакие формулы required history / warmup / lookback из indicator period, shift, crossing, methods не создавались (полностью удалены в rev 1–2).
- Никакие default-значения для timeframe/lookback не подставляются: missing → явный fail цикла (`TimeframeNotConfigured` / `LookbackNotConfigured`).
- `MarketSnapshot` собирается только из реальных broker-данных (last price + свечи); синтетические значения не подставляются.
- Единственная вычислительная деталь: окно range-запроса к брокеру = `lookback_bars + 1` bar-width по времени — это деталь преобразования «N свечей → временной диапазон» для range query (чтобы в запрос попала текущая формирующаяся свеча), а НЕ Veles warmup/lookback rule. Количество свечей определяет брокер в пределах окна; контракт остаётся ровно `lookback_bars`.
- Timeframe и lookback берутся только из конфигурации стратегии бота (per-bot), глобального runtime timeframe нет.

## 7. Известные ограничения

1. **`PROJECT_STATE.md` отсутствует в репозитории** (referenced AGENTS.md §1/§7 как canonical recovery document, но никогда не создан). Вывод состояния выполнен из Git (branches, logs, diff) и `.agent/*` — gap зафиксирован, файл не создавался в рамках MVP-6.10 (out of scope).
2. Окончательное окно fetch-запроса может вернуть до `lookback_bars + 1` свечи (включая формирующуюся) — см. пункт 6; при необходимости review может потребовать точного отсечения в `get_snapshot`.
3. `MarketDataService.get_snapshot` пока не покрывает retry/timeout политики за пределами существующих механизмов service (out of scope MVP-6.10).
4. Backtest path не использует `MarketSnapshot`/`lookback_bars` (Backtest timeframes живут в `BacktestConfig`) — намеренная граница.
5. Авторитетный position-sizing источник отсутствует (MVP-6.8 boundary): `process()` блокирует live-выполнение с `SizingNotConfigured` — ограничение сохранено без изменений.

## 8. Итог

MVP-6.10 реализован на `agent/review/mvp-6.10` (final `c7429fd`), обе review-замечания устранены, вся валидация пройдена, master не изменён. **Ожидаем повторное независимое ревью ChatGPT; accepted не объявляем.**
