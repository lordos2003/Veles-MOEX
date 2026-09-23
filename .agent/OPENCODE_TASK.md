# OpenCode Agent Control

## STATUS
REPORT

## TASK_ID
MVP-6.3

## TASK
Исправить MVP-6.3 поверх commit `a4eaac975f59454c14b980fe3234af2bd2a2d8bf`.

Только два текущих блокера.

### 1. Убрать lot_size fallback

В `TInvestAdapter._to_order()` всё ещё есть:

```python
factor = Decimal(lot_size) if lot_size else Decimal("1")
```

Удалить fallback.

Если для order с FIGI `lot_size` отсутствует или некорректен:

- не возвращать BrokerOrder;
- выбросить явную broker/integration error;
- recovery/live execution остаётся BLOCKED;
- не добавлять T-Invest детали в trading domain.

Добавить deterministic test.

### 2. Не проглатывать unary recovery errors

В `TInvestStreamManager._recover()` ошибки `get_orders()` и `get_open_positions()` сейчас только логируются.

Это запрещено.

Если unary recovery завершилась ошибкой:

- recovery должна вернуть failure/SAFE=false;
- full recovery не должна разрешить dispatch;
- live execution остаётся BLOCKED;
- stream не должен продолжать обработку live events;
- reconnect должен повторить recovery при следующей попытке.

Сохранить порядок:

`connect/resubscribe → unary recovery → full durable recovery → SAFE → dispatch`.

Добавить deterministic tests:
- ошибка `get_orders()` блокирует dispatch;
- ошибка `get_open_positions()` блокирует dispatch;
- после failed recovery события не обрабатываются.

### Не менять

- T-Invest MCP;
- DCA/Grid;
- Exit Engine;
- Risk Manager;
- Strategy;
- Backtest;
- другие брокеры;
- OrderStateStream-only;
- финансовые параметры;
- persistence schema;
- unrelated refactoring.

### Validation

Запустить:

- `pytest`
- `ruff`
- `npm build`

### Git

- Один focused correction commit.
- НЕ push master.
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

MVP-6.3 — CORRECTION REQUIRED task applied. Committed on `master` over
`a4eaac9`; correction commit `1907c24`.

### What was fixed (two blockers)
1. **lot_size fallback removed.** `TInvestAdapter._to_order()` no longer contains
   `factor = Decimal(lot_size) if lot_size else Decimal("1")`. For an order with a
   FIGI, the lot size must resolve to a positive value or `InvalidRequestError`
   is raised (never a false canonical quantity). For an order without a FIGI that
   still carries a non-zero lot quantity, an `InvalidRequestError` is also raised
   (cannot normalize without an instrument). The only `factor = Decimal("1")`
   path is a zero-quantity, no-FIGI order (units resolve to 0). The error stays
   inside the broker integration boundary; the trading domain remains
   broker-neutral.
2. **Unary recovery errors are no longer swallowed.** `TInvestStreamManager._recover()`
   now returns `bool` (True only when both `get_orders()` and `get_open_positions()`
   succeed). On failure `_run_session()` does not dispatch live events and raises
   `ConnectionError`, so the `run()` loop reconnects and retries recovery. The
   sequence is preserved: connect/resubscribe -> unary recovery -> full durable
   recovery -> SAFE gate -> dispatch.

### Files changed
- backend/app/brokers/tinvest.py (`_to_order` lot-size guard)
- backend/app/brokers/tinvest_streams.py (`_recover` returns bool; `_run_session` gates)
- backend/tests/test_tinvest_adapter.py (new `test_order_without_figi_but_quantity_rejected`)
- backend/tests/test_tinvest_streams.py (new unary-recovery failure tests)

### Tests and exact results
New deterministic tests:
- `test_lot_size_unavailable_blocks_order_normalization` (figi order -> raises)
- `test_order_without_figi_but_quantity_rejected` (no-figi + quantity -> raises)
- `test_unary_order_recovery_error_blocks_dispatch`
- `test_unary_position_recovery_error_blocks_dispatch`

Full backend suite: `266 passed, 1 skipped` (was `263 passed, 1 skipped`; +3).
The single skip is the opt-in live sandbox integration test (no credentials).

### ruff result
`All checks passed!` (app + tests).

### npm build result
`✓ built in 3.16s` (vite, 32 modules).

### commit SHA
Correction commit `1907c245f49a66678ab7c204fcafdefb7c482fd9` —
`fix: harden lot-size normalization and unary recovery gating`
(branch `master`, NOT pushed), on top of `a4eaac9`. Published to
`agent/review/mvp-6.3`.

### git status / git log -5
- `git status`: branch `master`, ahead of `origin/master` by 5, working tree
  clean (verification done before checkout to `agent/control` for this report).
- `git log -5 --oneline`:
  - `1907c24` fix: harden lot-size normalization and unary recovery gating
  - `a4eaac9` fix: wire production live runtime and harden lot-size normalization
  - `fd10067` fix: finalize MVP-6.3 unit normalization and recovery wiring
  - `b9869d9` fix: complete MVP-6.3 recovery wiring and broker-fact reconciliation
  - `3720b7c` feat: implement live state reconciliation and recovery

### Divergence / blocked conditions
- None. No merge/rebase performed; `master` NOT pushed (ahead of
  `origin/master` by 5). `## CHATGPT REVIEW` was not modified.

## CHATGPT REVIEW

### Результат независимой проверки

Commit `3720b7ca3548ae6339a5c7597c59923634f5ee77` опубликован в review-ветке и фактический diff проверен.

MVP-6.3 **пока не принимается**.

Основные причины:

1. **Startup recovery не подключён к реальному application startup.**
   `LiveRecoveryCoordinator` существует, но `app/main.py` и текущий composition/dependency path его не запускают. Поэтому требование «reconciliation completed before live execution resumes» фактически не выполняется.

2. **Reconnect recovery не подключён к OrderStateStream.**
   В текущем diff нет интеграции `LiveRecoveryCoordinator.recover()` с фактическим reconnect/resubscribe flow. Само наличие метода `recover()` не выполняет требование «resubscribe → unary reconciliation → resume».

3. **Reconciliation order не восстанавливает фактические fill quantities / average fill price из broker order.**
   `LiveRecoveryCoordinator` передаёт в `OrderUpdate` только status/reject/idempotency/broker order ID. `BrokerOrder.executed_quantity` и фактическая цена не используются. Следовательно, локальный `filled_quantity`/average fill price может остаться устаревшим даже при найденном broker order.

4. **Reconciliation positions не удаляет/обнуляет stale local positions, отсутствующие среди broker open positions.**
   Код применяет только позиции, которые вернул broker. Если локально сохранена позиция, а broker уже показывает её отсутствие, она остаётся в `PositionManager`. Это нарушает требование «broker facts over stale local state».

5. **Fill reconciliation не реализована в требуемом смысле.**
   В отчёте указано, что recovery опирается на persisted fills + будущую stream deduplication. Но после restart/recovery текущий код не получает отсутствующие broker executions и не восстанавливает их из broker facts. Наличие persisted fills само по себе не восстанавливает fills, произошедшие после последнего durable snapshot.

Эти пункты относятся непосредственно к обязательному scope MVP-6.3, поэтому это не «последующий integration step», а незавершённая часть текущей задачи.

### Проверенные положительные части

- Commit действительно содержит durable ORM state и Alembic migration.
- Есть broker-neutral `LiveStateStore` boundary.
- Есть `SqlAlchemyLiveStateStore`.
- Есть deterministic tests, включая duplicate trade, lost response и stale order/position cases.
- `OrderStateStream-only` решение не изменено.
- В domain не внесена зависимость от SQLAlchemy/T-Invest.
- По REPORT: `248 passed, 1 skipped`, ruff passed, npm build passed.

## CORRECTION TASK

Исправить MVP-6.3 поверх commit `3720b7ca3548ae6339a5c7597c59923634f5ee77`.

Обязательные исправления:

1. Подключить startup recovery к фактическому production composition/startup path проекта. До разрешения live execution должен быть выполнен `LiveRecoveryCoordinator.recover()`; при `BLOCKED` новые execution должны быть запрещены.

2. Подключить тот же recovery flow к фактическому OrderStateStream reconnect/resubscribe path:
   - reconnect;
   - resubscribe;
   - unary reconciliation;
   - только затем продолжение live events.
   TradesStream не возвращать.

3. При reconciliation broker order использовать фактические broker quantity/fill/average-price facts, доступные через существующий BrokerAdapter, и приводить InternalOrder к broker state.

4. При reconciliation positions сделать broker authoritative: локальные позиции, которых нет среди broker open positions, должны быть приведены к фактическому broker state, а не оставаться stale.

5. Реализовать восстановление отсутствующих executions/fills из доступных broker facts/OrderStateStream data так, чтобы restart/reconnect не терял executions между последним snapshot и recovery. Сохранить dedup по trade/execution ID.

6. Добавить deterministic tests именно на эти случаи:
   - startup recovery реально вызывается до разрешения execution;
   - reconnect реально вызывает reconciliation до resume;
   - broker executed quantity/average price заменяют stale local values;
   - stale local position исчезает, если broker её больше не показывает;
   - execution, произошедший после последнего snapshot, восстанавливается без двойного применения.

Не менять:
- T-Invest MCP;
- DCA/Grid/Exit logic;
- Risk Manager;
- другие брокеры;
- OrderStateStream-only решение;
- финансовые параметры.

Git:
- не создавать новый несвязанный commit;
- сделать focused correction commit с понятным сообщением;
- master не push;
- merge/rebase не выполнять;
- после исправления опубликовать REPORT на agent/control;
- `CHATGPT REVIEW` не изменять.

Остановиться после публикации REPORT для повторной независимой проверки.

## FINAL CORRECTION TASK

Исправить MVP-6.3 поверх commit:

fd10067bebce7baea06f899a63a4a5826bc3b28d

Это финальная targeted correction. Не расширять scope.

### 1. Подключить OrderStateStream к реальному production live runtime

Сейчас LiveExecutionService.build_stream_manager() корректно создаёт TInvestStreamManager с recovery hook, но production startup в app/main.py создаёт только LiveExecutionService и вызывает service.start(). Production runtime фактически не запускает TInvestStreamManager.

Нужно:

- в production composition реально создать TInvestStreamManager через LiveExecutionService.build_stream_manager(...);
- использовать существующий production T-Invest OrderStateStream transport;
- запустить stream manager в live runtime после успешного startup recovery;
- корректно остановить/закрыть stream manager при shutdown;
- не создавать второй отдельный recovery path;
- reconnect должен проходить через уже реализованный:
  connect/resubscribe → unary recovery → full durable recovery → SAFE → dispatch;
- при BLOCKED/failed recovery новые live events и новые execution должны оставаться заблокированными;
- сохранить OrderStateStream-only решение;
- TradesStream не возвращать.

ВАЖНО:
Не делать stream manager только тестовым объектом. Должна существовать реальная production composition path от app lifespan до TInvestStreamManager.run().

Добавить deterministic test, доказывающий production composition:
startup → stream manager создан/запущен → reconnect recovery → resume.
И test shutdown, что stream manager останавливается.

### 2. Убрать небезопасный lot_size fallback

В TInvestAdapter._to_order() сейчас при невозможности определить lot_size используется:

factor = Decimal("1")

Это запрещено.

BrokerOrder contract требует canonical instrument units.

Если для T-Invest order с FIGI невозможно получить корректный lot_size:

- НЕ считать lots canonical units;
- НЕ возвращать потенциально неверный BrokerOrder;
- завершить normalization/recovery с явной broker/integration error;
- live execution/recovery должен остаться BLOCKED/UNSAFE;
- ошибка должна оставаться внутри broker integration boundary;
- не добавлять broker-specific логику в trading domain.

Удалить silent fallback lot_size -> 1.

Добавить deterministic test:
- lot_size unavailable;
- TInvestAdapter не возвращает ложный canonical quantity;
- recovery/live execution не становится SAFE.

### 3. Проверить startup failure semantics

Если создание/запуск live stream manager или его initial recovery не удалось:

- live execution не должно становиться доступным;
- API application может продолжить работу в read-only режиме;
- service.can_execute должно оставаться False;
- не должно существовать обходного пути для submit().

Не менять существующую модель SAFE/BLOCKED.

### 4. Не менять

Не менять:
- T-Invest MCP;
- DCA/Grid;
- Exit Engine;
- Risk Manager;
- Strategy Engine;
- Backtest;
- другие брокеры;
- OrderStateStream-only архитектуру;
- финансовые параметры;
- persistence schema без необходимости;
- unrelated refactoring.

### 5. Tests / validation

Добавить deterministic tests минимум на:
1. production lifespan/composition реально запускает stream manager;
2. startup recovery must be SAFE before stream events resume;
3. stream manager shutdown;
4. reconnect recovery remains the gate;
5. lot_size unavailable blocks normalization/recovery;
6. submit remains blocked after stream/startup failure.

Запустить:
- pytest
- ruff
- npm build

### 6. Git protocol

- Один focused correction commit.
- НЕ push master.
- НЕ merge.
- НЕ rebase.
- Опубликовать correction commit в agent/review/mvp-6.3.
- REPORT записать в agent/control.
- CHATGPT REVIEW НЕ изменять.
- После REPORT остановиться для независимой проверки ChatGPT.

В REPORT обязательно указать:
- commit SHA;
- production composition path;
- где создаётся и запускается TInvestStreamManager;
- shutdown path;
- что происходит при startup/stream failure;
- как устранён lot_size fallback;
- результаты pytest/ruff/npm build;
- git status и git log -5.
