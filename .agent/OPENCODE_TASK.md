# OpenCode Agent Control

## STATUS
REPORT

## TASK_ID
MVP-6.3-CORRECTION-LOT-SIZE

## TASK

Исправить **только текущий оставшийся blocker MVP-6.3**.

Базовый commit: `1907c245f49a66678ab7c204fcafdefb7c482fd9`.

Проверка показала, что в `backend/app/brokers/tinvest.py` fallback всё ещё существует:

```python
factor = Decimal("1")
```

Он находится в ветке order без FIGI и с нулевыми quantity.

Это всё равно нарушает требование предыдущей задачи: **не должно быть fallback lot_size → 1**.

### Исправление

В `TInvestAdapter._to_order()`:

1. Удалить `factor = Decimal("1")` полностью.
2. Не использовать коэффициент `1` как замену отсутствующему `lot_size`.
3. Для order с FIGI сохраняется существующая проверка положительного `lot_size`.
4. Для order без FIGI:
   - если `lotsRequested` или `lotsExecuted` ненулевые — сохранить явный `InvalidRequestError`;
   - если quantity равен нулю — вернуть корректный нулевой canonical quantity **без использования fallback factor**.
5. Не менять broker-neutral domain.

### Test

Добавить или изменить deterministic test, который явно подтверждает:

- в `_to_order()` нет silent fallback `lot_size -> 1`;
- zero-quantity/no-FIGI order обрабатывается без fallback;
- non-zero quantity/no-FIGI остаётся `InvalidRequestError`.

### Не менять

- T-Invest MCP;
- OrderStateStream;
- recovery logic;
- LiveExecutionService;
- DCA/Grid;
- Exit Engine;
- Risk Manager;
- Strategy;
- Backtest;
- другие брокеры;
- persistence schema;
- unrelated refactoring.

### Validation

Запустить:

- `pytest`
- `ruff`
- `npm build`

### Git

- Один focused correction commit.
- НЕ push `master`.
- НЕ merge.
- НЕ rebase.
- Опубликовать commit в `agent/review/mvp-6.3`.
- REPORT записать в `agent/control`.
- `CHATGPT REVIEW` НЕ изменять.
- После REPORT остановиться.

REPORT должен содержать:

- commit SHA;
- что исправлено;
- pytest;
- ruff;
- npm build;
- git status;
- git log -5.

## REPORT

MVP-6.3-CORRECTION-LOT-SIZE — applied. Committed on `master` over `1907c24`;
correction commit `3b381d6`.

### What was fixed
Removed the last silent `lot_size -> 1` fallback in `TInvestAdapter._to_order()`.
The `factor = Decimal("1")` branch is gone entirely. `_to_order()` now:

- For an order **with** a FIGI: requires a positive `lot_size` (fetched via
  `get_instrument`); otherwise it raises `InvalidRequestError` (never a false
  canonical quantity).
- For an order **without** a FIGI:
  - if `lotsRequested`/`lotsExecuted` are non-zero -> raises
    `InvalidRequestError` (cannot normalize without an instrument);
  - if quantity is zero -> returns **zero** canonical units and an empty
    `executions` list, without using any fallback factor of 1.

The broker-neutral trading domain is unchanged; `Decimal` is kept.

### Files changed
- backend/app/brokers/tinvest.py (`_to_order` no-factor restructure)
- backend/tests/test_tinvest_adapter.py (new tests)

### Tests and exact results
New deterministic tests:
- `test_to_order_has_no_silent_lot_fallback` (asserts `factor = Decimal("1")`
  is not present in `_to_order`)
- `test_zero_quantity_no_figi_order_returns_zero_units` (zero-quantity/no-FIGI
  maps to zero units, no fallback)
- existing `test_order_without_figi_but_quantity_rejected` (non-zero/no-FIGI
  raises `InvalidRequestError`) still passes.

Full backend suite: `268 passed, 1 skipped` (was `266 passed, 1 skipped`; +2).
The single skip is the opt-in live sandbox integration test (no credentials).

### ruff result
`All checks passed!` (app + tests).

### npm build result
`✓ built in 2.86s` (vite, 32 modules).

### commit SHA
Correction commit `3b381d68fc31d6ac37053539e869a908d6517e2e` —
`fix: remove lot-size fallback for zero-quantity orders`
(branch `master`, NOT pushed), on top of `1907c24`. Published to
`agent/review/mvp-6.3`.

### git status / git log -5
- `git status`: branch `master`, ahead of `origin/master` by 6, working tree
  clean (verification done before checkout to `agent/control` for this report).
- `git log -5 --oneline`:
  - `3b381d6` fix: remove lot-size fallback for zero-quantity orders
  - `1907c24` fix: harden lot-size normalization and unary recovery gating
  - `a4eaac9` fix: wire production live runtime and harden lot-size normalization
  - `fd10067` fix: finalize MVP-6.3 unit normalization and recovery wiring
  - `b9869d9` fix: complete MVP-6.3 recovery wiring and broker-fact reconciliation

### Divergence / blocked conditions
- None. No merge/rebase performed; `master` NOT pushed (ahead of
  `origin/master` by 6). `## CHATGPT REVIEW` was not modified.


## CHATGPT REVIEW

### Результат независимой проверки

MVP-6.3 **ПРИНЯТО**.

Проверен фактический commit:

`3b381d68fc31d6ac37053539e869a908d6517e2e`

Проверка выполнена относительно предыдущего принятого correction base:

`1907c245f49a66678ab7c204fcafdefb7c482fd9`

Фактический diff содержит только:
- `backend/app/brokers/tinvest.py`
- `backend/tests/test_tinvest_adapter.py`

Проверено:

1. `factor = Decimal("1")` полностью удалён из `TInvestAdapter._to_order()`.
2. Order с FIGI требует положительный `lot_size`.
3. Order без FIGI с ненулевым quantity получает `InvalidRequestError`.
4. Zero-quantity/no-FIGI order получает явные `Decimal("0")` без fallback.
5. Добавлены deterministic tests для отсутствия fallback и zero-quantity case.
6. Предыдущие recovery/startup/reconnect исправления в этом commit не изменены.
7. По REPORT: `268 passed, 1 skipped`, ruff passed, npm build passed.
8. `master` не push, merge/rebase не выполнялись.

**MVP-6.3 принят.**

Следующее действие: можно перенести принятые изменения в `master` по установленному Git workflow.