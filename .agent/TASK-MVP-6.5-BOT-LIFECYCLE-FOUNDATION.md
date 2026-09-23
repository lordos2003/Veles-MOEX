# OpenCode Task — MVP-6.5 Bot Lifecycle Foundation

## TASK_ID

MVP-6.5-BOT-LIFECYCLE-FOUNDATION

## STATUS

TASK

## Goal

Создать минимальный реальный Bot Lifecycle, который станет основой для последующей интеграции RiskManager и Strategy/Trading runtime.

Текущий MVP-6.5 был остановлен после аудита: production Bot Lifecycle отсутствует. Не создавать обходной или фиктивный lifecycle.

## Architecture decided by ChatGPT

Основная модель:

```
Bot
 ├─ Strategy Version
 ├─ Instrument
 ├─ Direction
 ├─ State
 ├─ Trading configuration
 └─ Risk configuration
          |
      Bot Runtime
          |
      Strategy Engine
          |
      Trading Engine
          |
      Risk Manager
          |
      Order Manager
          |
      BrokerAdapter
```

Bot — это persisted application entity.

Bot Runtime — runtime state/controller for one bot.

TradingEngine остаётся broker-neutral и не знает T-Invest.

RiskManager остаётся broker-neutral.

Broker connection остаётся общим live runtime. Bot lifecycle не создаёт отдельное broker connection.

## Bot states

Минимальная state machine:

- STOPPED — бот не исполняет новые intents.
- STARTING — выполняется запуск.
- RUNNING — бот может генерировать и отправлять intents.
- STOP_REQUESTED — новые intents запрещены; runtime завершает остановку.
- ERROR — runtime остановлен из-за ошибки.
- EMERGENCY_STOP — аварийная остановка; новые intents запрещены, active bot orders должны быть отменены, если существующий broker-neutral OrderManager path это поддерживает.

Разрешённые переходы:

- STOPPED -> STARTING
- STARTING -> RUNNING
- STARTING -> ERROR
- RUNNING -> STOP_REQUESTED
- RUNNING -> EMERGENCY_STOP
- RUNNING -> ERROR
- STOP_REQUESTED -> STOPPED
- STOP_REQUESTED -> ERROR
- ERROR -> STARTING
- EMERGENCY_STOP -> STOPPED

Не добавлять другие состояния без необходимости.

## Lifecycle semantics

### START

START должен:

1. найти существующий Bot;
2. проверить, что Bot может быть запущен;
3. вызвать RiskManager.check_start(bot_id) до перехода в RUNNING;
4. зарегистрировать bot как active в RiskManager только после успешного start guard;
5. перевести Bot в RUNNING;
6. разрешить runtime processing.

START не должен создавать отдельное broker connection.

### Normal STOP

STOP должен:

1. перевести Bot в STOP_REQUESTED;
2. запретить новые execution intents;
3. отменить активные orders этого Bot, если существующий OrderManager предоставляет broker-neutral путь;
4. НЕ закрывать позицию автоматически;
5. завершить runtime;
6. вызвать RiskManager.stop_bot(bot_id);
7. перевести Bot в STOPPED.

Normal STOP не является close-position.

### EMERGENCY STOP

EMERGENCY_STOP должен:

1. немедленно запретить новые execution intents;
2. установить аварийное состояние Bot;
3. отменить активные orders этого Bot через существующий broker-neutral path, если он доступен;
4. НЕ открывать новые позиции;
5. НЕ выполнять автоматическое закрытие позиции, если такого поведения нет в существующей модели;
6. не создавать broker-specific code в lifecycle.

## Data model

Проверить существующую ORM Bot model и использовать её как основу.

Не создавать вторую Bot сущность.

Нужны только поля, которые реально необходимы для lifecycle:

- id
- state/status
- strategy reference, если поле уже предусмотрено существующей моделью
- instrument reference, если поле уже предусмотрено существующей моделью
- timestamps только если существующая persistence pattern требует их

Если текущая schema не содержит необходимых lifecycle данных, изменить schema минимально.

Не добавлять финансовые параметры по умолчанию.

Risk configuration не выдумывать.

## Bot Repository / Service

Создать broker-neutral application layer только в объёме, необходимом для lifecycle:

- BotRepository: load/save/update state;
- BotService или BotRuntimeManager: START/STOP/EMERGENCY_STOP.

Не создавать микросервис.

Не создавать отдельную event bus систему.

Не создавать новый persistence subsystem.

## Integration with current runtime

Интеграция должна сохранить:

- LiveRecoveryCoordinator;
- SAFE/BLOCKED execution gate;
- OrderStateStream;
- idempotency;
- PositionManager;
- OrderManager;
- TradingEngine;
- RiskManager;
- T-Invest adapter boundary.

Bot lifecycle должен стать upstream control layer:

Bot Runtime -> TradingEngine -> RiskManager -> OrderManager -> Broker.

Если существующий StrategyEngine/config source отсутствует, не создавать fake strategy source. Зафиксировать это как следующий integration boundary.

## Execution gate

Для Bot в STOPPED, STOP_REQUESTED, ERROR, EMERGENCY_STOP новые intents должны быть запрещены.

RUNNING — единственное состояние, из которого разрешена генерация/отправка новых intents.

Проверка Bot state должна быть broker-neutral.

## RiskManager integration

После создания реального Bot lifecycle:

- START вызывает RiskManager.check_start(bot_id);
- успешный START вызывает RiskManager.start_bot(bot_id);
- STOP/ERROR/EMERGENCY_STOP вызывают RiskManager.stop_bot(bot_id) при завершении active runtime;
- RiskManager остаётся authoritative order guard;
- не добавлять финансовые лимиты без существующего configuration source.

## API

Проверить текущий API.

Если существующего bot API нет, добавить минимальные broker-neutral endpoints:

- GET /bots
- GET /bots/{bot_id}
- POST /bots/{bot_id}/start
- POST /bots/{bot_id}/stop
- POST /bots/{bot_id}/emergency-stop

Не добавлять UI в эту задачу.

Не добавлять authentication/authorization subsystem, если его ещё нет.

## Tests

Добавить deterministic tests для:

1. valid STOPPED -> STARTING -> RUNNING;
2. RiskManager.check_start blocks START;
3. successful START registers active bot;
4. STOP blocks new intents;
5. normal STOP does not close position;
6. EMERGENCY_STOP blocks new intents;
7. EMERGENCY_STOP cancels active orders only through existing broker-neutral path, if available;
8. invalid state transitions are rejected;
9. TradingEngine remains broker-neutral;
10. existing SAFE/BLOCKED recovery gate remains authoritative.

Не создавать fake broker implementation beyond existing test doubles.

## Important scope boundary

Do NOT implement Strategy -> TradingEngine production composition in this task unless an existing real Strategy/config source is already present.

Do NOT invent StrategyConfig risk fields.

Do NOT invent financial defaults.

Do NOT implement new trading logic.

Do NOT change DCA/Grid.

Do NOT change Exit Engine.

Do NOT change Backtest.

Do NOT change T-Invest transport.

Do NOT change OrderStateStream.

Do NOT change recovery algorithm except the minimum Bot-state gate required for lifecycle integration.

## Documentation

Update the relevant architecture/task documentation to describe the implemented Bot Lifecycle.

Document any remaining boundary:

- Strategy source absent;
- risk configuration source absent;
- any missing broker-neutral order cancellation path.

Do not claim functionality as production-integrated unless the code actually wires it.

## Validation

Run:

- pytest
- ruff check app tests scripts
- frontend npm run build

## Git workflow

- Work from current accepted master: `3ce159f4ac2b49088a53ce70cd0d24a3f5a5b684`.
- Create one focused implementation commit.
- Do NOT push master.
- Do NOT merge.
- Do NOT rebase.
- Publish implementation to `agent/review/mvp-6.5`.
- Create separate report `.agent/REPORT-MVP-6.5.md` on `agent/control`.
- Do NOT modify `CHATGPT REVIEW`.
- Stop after REPORT.

REPORT must contain:

- commit SHA;
- exact lifecycle implementation;
- state transition table;
- changed files;
- RiskManager integration;
- API integration, if implemented;
- remaining boundaries;
- pytest;
- ruff;
- npm build;
- git status;
- git log -5.
