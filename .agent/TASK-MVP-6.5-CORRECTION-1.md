# OpenCode Task — MVP-6.5 Correction #1

## TASK_ID

MVP-6.5-CORRECTION-1-LIFECYCLE-CONSISTENCY

## STATUS

TASK

## Base

Review commit:

`9affc539a7653ab32e6517fe994f7b3f7cca5c03`

Current review branch:

`agent/review/mvp-6.5`

## Goal

Исправить только реальные lifecycle consistency blockers, найденные независимой проверкой.

Не расширять scope.

## Blocker 1 — disconnected fallback BotRuntimeManager

Текущий `get_bot_runtime_manager()` создаёт новый `BotRuntimeManager(RiskManager())`, если production `live_execution` отсутствует.

Это недопустимо для mutating Bot API.

Нельзя переводить persisted Bot в RUNNING через runtime, который не связан с production execution path.

Требование:

- Для `POST /bots/{id}/start`
- Для `POST /bots/{id}/stop`
- Для `POST /bots/{id}/emergency-stop`

использовать только реальный application BotRuntimeManager, связанный с live execution service.

Если live execution service/runtime manager отсутствует:

- mutation должен быть отклонён;
- не изменять Bot state;
- не создавать fallback RiskManager/RuntimeManager;
- вернуть явную API error.

GET endpoints должны продолжать работать независимо.

Не создавать новый broker connection.

## Blocker 2 — persisted state vs runtime state после restart

Сейчас Bot.status сохраняется в DB, но BotRuntimeManager после restart пуст.

Не допускать состояния:

```
DB: RUNNING
Runtime: no runtime
RiskManager: no active bot
```

Требование:

- При создании/инициализации production BotRuntimeManager восстановить persisted bot states из существующего BotRepository/ORM.
- Для persisted `RUNNING` не считать bot автоматически безопасно RUNNING без необходимой runtime initialization.
- Выбрать минимальную корректную семантику из существующего lifecycle:
  - либо восстановить runtime в состоянии, которое блокирует execution до явного START;
  - либо перевести persisted RUNNING в безопасное состояние ERROR/STOPPED и синхронизировать DB.
- Не выполнять автоматический `RiskManager.start_bot()` после process restart без явного START.
- Не создавать fake recovery logic.

Главное требование: после restart DB и runtime не должны противоречить друг другу относительно возможности execution.

Если для корректного восстановления нужен существующий application startup hook, использовать его. Не создавать отдельный persistence subsystem.

## Blocker 3 — STOP order

Текущий порядок:

```
STOP_REQUESTED
-> RiskManager.stop_bot()
-> cancel active orders
-> STOPPED
```

Это неправильно.

Требуемый порядок:

```
RUNNING
-> STOP_REQUESTED
-> block new intents
-> cancel active bot orders
-> finish stop
-> RiskManager.stop_bot()
-> STOPPED
```

То есть slot в `max_concurrent_bots` остаётся занятым во время cancellation.

Если cancellation завершается ошибкой:

- Bot должен перейти в ERROR;
- RiskManager state должен быть освобождён только после завершения lifecycle transition;
- не оставлять ложный RUNNING.

Normal STOP **не закрывает position**.

## Blocker 4 — START rejection persistence

Сейчас при RiskManager rejection:

```
runtime: ERROR
DB: STOPPED
```

Это недопустимо.

Требование:

- при rejected START persisted Bot state должен быть синхронизирован с фактическим lifecycle state;
- не возвращать успешный START;
- API должен вернуть явную ошибку;
- не оставлять DB в RUNNING.

Использовать существующий BotRepository.

## API error handling

Добавить минимальную обработку lifecycle errors в mutating endpoints:

- Bot not found -> 404;
- disconnected/unavailable live runtime -> явная 409/503;
- invalid lifecycle transition -> 409;
- RiskManager START rejection -> 409;
- lifecycle execution failure -> 409/503 в зависимости от существующего error model.

Не вводить новый общий error subsystem.

## EMERGENCY STOP

Сохранить текущую семантику:

- запрет новых intents;
- cancel active bot orders через существующий broker-neutral OrderManager;
- не закрывать position автоматически;
- не создавать broker-specific code.

После завершения emergency stop RiskManager должен больше не считать bot active.

## Tests

Добавить deterministic tests для конкретных blockers:

1. mutating API rejects when live BotRuntimeManager is unavailable;
2. GET bot endpoints still work without live runtime;
3. persisted RUNNING bot does not become executable after restart without explicit START;
4. STOP keeps RiskManager slot occupied while order cancellation is in progress;
5. cancellation failure leads to ERROR and consistent RiskManager state;
6. rejected START persists ERROR (or the chosen documented safe state) and returns API error;
7. no disconnected fallback RiskManager is created;
8. existing SAFE/BLOCKED recovery gate still blocks execution;
9. existing EMERGENCY_STOP behaviour remains correct.

Do not add fake broker behavior beyond existing test doubles.

## Documentation

Update relevant lifecycle documentation only where needed to describe the corrected semantics.

Document the chosen restart semantics for persisted RUNNING bots.

Do not claim production behavior that is not actually wired.

## Do not change

- Strategy Engine;
- TradingEngine.process();
- DCA/Grid;
- Exit Engine;
- Backtest;
- T-Invest transport;
- OrderStateStream;
- recovery algorithm, except the minimum lifecycle startup/state synchronization required by this task;
- financial parameters;
- risk defaults;
- broker-neutral boundaries;
- unrelated refactoring.

## Validation

Run:

- pytest
- ruff check app tests scripts
- npm run build

## Git workflow

- One focused correction commit.
- Do NOT push master.
- Do NOT merge.
- Do NOT rebase.
- Do NOT reset.
- Update `agent/review/mvp-6.5`.
- Create/update separate `.agent/REPORT-MVP-6.5.md` on `agent/control`.
- Do NOT modify `CHATGPT REVIEW`.
- Stop after REPORT.

REPORT must contain:

- correction commit SHA;
- exact fixes;
- chosen restart semantics;
- STOP ordering;
- START rejection persistence;
- API error behavior;
- changed files;
- pytest;
- ruff;
- npm build;
- git status;
- git log -5;
- review branch SHA.
