# OpenCode Agent Control

## STATUS
TASK

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
