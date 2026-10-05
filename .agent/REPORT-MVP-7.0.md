# REPORT-MVP-7.0 — Удобный локальный запуск, песочница и API для стратегий, ботов и бэктеста

## Статус

**Готово к независимому ревью.**

- Задача: `TASK-MVP-7.0-LOCAL-RUN-AND-API.md` (control @ `5010c55`, 2026-10-05)
- Контракт: R1–R8 (владелец, 2026-10-05)
- Ветка реализации: `agent/review/mvp-7.0` (от `master @ b01f8a8`)
- Коммит: `d06f98a` — **pushed, in sync with origin** (подтверждение `git ls-remote` в конце отчёта)
- Отчёт: `agent/control:.agent/REPORT-MVP-7.0.md` — коммит в `agent/control` также pushed

## Изменения

### R1 — запуск одной командой (Windows, Docker Desktop)

- `.env.example` в корне репозитория: `TINVEST_TOKEN=`, `TINVEST_SANDBOX=true`,
  `LIVE_TRADING_ENABLED=false`, `BACKTEST_MAX_CANDLES=10000` и служебные
  переменные, комментарии по-русски. `.env` в `.gitignore`, `!.env.example`.
- `docker-compose.yml`: сервис `backend` читает корневой `.env`
  (`env_file: [{path: .env, required: false}]` — без `.env` сервис стартует,
  интеграция T-Invest в состоянии `not_configured`); команда при старте
  `sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"`
  (ошибка миграции → контейнер не поднимается); все порты (postgres 5432,
  redis 6379, backend 8000, frontend 5173) публикуются **только на
  `127.0.0.1`**.
- `README.md`: раздел «Быстрый старт (Windows)» — PowerShell: `Copy-Item
  .env.example .env`, вписать токен песочницы, `docker compose up --build -d`,
  проверка `/api/health` и `/docs`; ссылка на получение токена — официальная
  документация T-Invest (`https://tinkoff.github.io/investAPI/token/`, раздел
  «Токен песочницы»).
- Значения по умолчанию `.env.example` — безопасные: песочница включена,
  живая торговля выключена. Без `.env` токен пуст → адаптер
  `not_configured` (как и было).

### R2 — счета

- `backend/app/services/accounts.py` (новый): `AccountService` — локальный
  источник счетов; `sync_from_broker` — upsert по `(broker, external_account_id)`
  без дублей (существующие обновляются по имени/активности, отсутствующие
  у брокера не удаляются); `local_by_broker_ids` — внешние id → локальные id.
- `backend/app/api/tinvest.py`: `POST /api/accounts/sync` →
  `{"synced": <int>}`; `GET /api/accounts` дополнен полями `id` (локальный
  id, `null` если не сохранён) и `is_saved` (bool) в `AccountInfoResponse`.

### R3 — песочница T-Invest

- `backend/app/api/sandbox.py` (новый) + `backend/app/schemas/sandbox.py`:
  `POST /api/sandbox/accounts` (OpenSandboxAccount + сразу upsert в `accounts`
  по правилу R2), `POST /api/sandbox/accounts/{id}/pay-in` (`amount` Decimal>0
  и `currency` — обязательные, без умолчаний; совпадение id в path и теле),
  `DELETE /api/sandbox/accounts/{id}` (CloseSandboxAccount). Все три → **409**
  при `TINVEST_SANDBOX=false` (`SandboxUnsupportedError`, глобальный
  обработчик).
- `backend/app/brokers/base.py`, `backend/app/brokers/tinvest.py`,
  `backend/app/brokers/__init__.py`: брокер-нейтральные `open_sandbox_account`
  / `sandbox_pay_in` / `close_sandbox_account`; маппинг в T-Invest
  `SandboxService` (`OpenSandboxAccount`, `SandboxPayIn`, `CloseSandboxAccount`)
  внутри адаптера; типы T-Invest наружу не выходят.
- **Стоп-заявки в песочнице отсутствуют** (см. «Песочница по офиц. докам») —
  поэтому START бота, у которого в конфиге задан `exit.stop_loss`, в
  песочнице → **409** с явной причиной. Проверка — в
  `backend/app/api/bots.py` (`start_bot` получает брокера; gate
  `broker.supports_stop_orders` → `StrategyLoadError`-аналог/409; в бою:
  `supports_stop_orders=False` у адаптера в sandbox). Сигнатура
  `start_bot(bot_id, repo, runtime, session, broker)` расширена, существующие
  проверки D1/E3/E4/Risk не изменены.

### R4 — стратегии

- `backend/app/strategies/service.py` (новый) + `backend/app/strategies/schemas.py`
  (новый) + `backend/app/api/strategies.py` (новый):
  - `POST /api/strategies` `{name, description?, config}` → 201, создаются
    `Strategy` + неизменяемый `StrategyVersion` v1; ошибка валидации → 422 с
    перечнем полей;
  - `GET /api/strategies`, `GET /api/strategies/{id}` (с последней версией),
    `GET /api/strategies/{id}/versions` (новые сверху), `PUT /api/strategies/{id}` —
    новая конфигурация → новая неизменяемая версия `version + 1`, старые не
    меняются (404 при отсутствии);
  - `GET /api/strategies/schema` — JSON Schema `StrategyConfig` из pydantic
    (`title`/`description`/`enum` сохранены, новых значений по умолчанию нет);
  - `POST /api/strategies/validate` — `{config}` → `{valid, live_deal:
    {supported, reason}}` через `validate_live_deal_config()` (D1/E3/E4).

### R5 — боты

- `backend/app/bots/schemas.py` (+`BotCreate`, `BotUpdate`),
  `backend/app/bots/repository.py` (+`update_deposit`, `update_strategy_version`,
  `delete`), `backend/app/api/bots.py`:
  - `POST /api/bots` `{name, strategy_version_id, account_id, instrument_id,
    deposit?}` → 201, бот сразу в **STOPPED**; проверки существования →
    404, deposit ≤ 0 → 422;
  - `PATCH /api/bots/{id}` — депозит (правила C5) и/или `strategy_version_id`;
    смена версии только у STOPPED и без незакрытой сделки, иначе **409**;
    версия должна существовать (404); пустой PATCH / `null` у версии → 422;
  - `DELETE /api/bots/{id}` — только STOPPED и без незакрытой сделки, иначе **409**.

### R6 — просмотр сделок бота

- `backend/app/bots/schemas.py` (+`DealResponse`, `DealLevelResponse`),
  `backend/app/api/bots.py`,
  `backend/app/persistence/deal_store.py` (+`get_open_for_bot`,
  `list_closed_for_bot`):
  - `GET /api/bots/{id}/deal` — незакрытая сделка: статус, направление, P0
    (`p0_price`), средняя цена (`average_price`), **объём позиции
    (`position_quantity` = Σ исполненных уровней)**, уровни сетки (цена,
    номинал, объём, статус, исполнено, order ids), TP (цена, объём), стоп
    (цена, объём, `sl_order_id`, **`sl_active`**: `null` — не настроен,
    `true` — заявка выставлена, `false` — настроен, но снят), `close_reason`,
    время; **нет сделки → `null`** (200);
  - `GET /api/bots/{id}/deals?limit=` — история закрытых сделок новые сверху,
    `close_reason` включён; `limit` ≥ 1 (422 иначе).
  - Источник — хранилище Deal (MVP-6.12); ничего не пересчитывается
    «для красоты» (`position_quantity`/`sl_active` — проекции сохранённых
    полей Deal).

### R7 — бэктест по API

- `backend/app/backtest/schemas.py` (новый) + `backend/app/api/backtests.py`
  (новый):
  - `POST /api/backtests` — `{strategy_version_id | config, instrument_id,
    timeframe, from, to, deposit, maker_fee, taker_fee, slippage}`; ровно один
    источник стратегии (`strategy_version_id` XOR `config`); комиссии,
    проскальзывание и депозит — **обязательные** (`ge=0`/`gt=0`), значения не
    придумываются;
  - свечи — `MarketDataService` → брокер по существующему пути
    (`from`/`to` в UTC), лимиты брокера — куски внутри сервиса;
  - `backtest_max_candles` (новая настройка приложения, 10000) — превышение →
    **422** с явным текстом;
  - запуск синхронный, результат **не сохраняется**; ответ: сводка
    `BacktestResult` + `deals[]` (с `reason`) + `orders[]` + `executions[]`;
  - нет `tick_size`/`lot_size` у инструмента → **422** (явная ошибка, как в
    live, без дефолтов); нет инструмента/версии → 404; `SizingError` → 422.

### R8 — бэктест считает объём от депозита, как live

- `backend/app/backtest/config.py`: `BacktestConfig` + `deposit`, `lot_size`;
  прежний `quantity` сохранён только для существующих тестов.
- `backend/app/backtest/engine.py`: `_deposit_entry` — при заданном депозите
  объём уровней считается **теми же функциями**, что в live:
  `deposit_to_base_nominal` (C2) и `round_grid_to_lot` (C3) из
  `app/trading/sizing.py`; SIMPLE и CUSTOM проходят через `DCAGridEngine.build`
  → `GridOrder` → округление до лотов.
- API R7 всегда использует депозит (`BacktestConfig(...deposit=payload.deposit,
  lot_size=instrument.lot_size...)`).
- **Изменённых существующих тестов бэктеста нет** (путь `quantity` не тронут);
  новая проверка совпадения бэктест-объёмов с live-расчётом — в
  `test_mvp70_api.py` (SIMPLE и CUSTOM).

## Документация

- `docs/architecture/TASK-10-LOCAL-RUN-AND-UI-MVP-7.md` (новый) — §1 MVP-7.0:
  запуск, переменные окружения, все новые эндпоинты (запрос/ответ/ошибки),
  песочница и что в ней поддерживается (со ссылками на офиц. документацию),
  ограничения (нет авторизации → только `127.0.0.1`).

## Песочница T-Invest — что поддерживается (офиц. документация)

Проверено 2026-10-05 по официальной документации Invest API
(`https://tinkoff.github.io/investAPI/`):

- Хост песочницы: `sandbox-invest-public-api.tinkoff.ru:443`
  (раздел «Песочница», `https://tinkoff.github.io/investAPI/head-sandbox/`).
- Доступен `SandboxService`: `OpenSandboxAccount`, `GetSandboxAccounts`,
  `CloseSandboxAccount`, `SandboxPayIn`, заявки (`PostSandboxOrder`,
  `ReplaceSandboxOrder`, `GetSandboxOrders`, `CancelSandboxOrder`,
  `GetSandboxOrderState`), портфель/позиции/операции, стримы
  (`PortfolioStream`, `PositionsStream`, `TradesStream`)
  (`https://tinkoff.github.io/investAPI/sandbox/`).
- **Стоп-заявок в песочнице НЕТ**: сервиса `SandboxStopOrdersService` в
  списке методов нет; в документации прямо: «В песочнице отсутствуют
  стоп-заявки, маржинальные показатели». Поэтому START бота со
  стоп-лоссом в песочнице → **409** с понятной причиной, без обходов.
- Маржинальные показатели — нет (для нашего пути не используются).

## Тесты

### Новые: `backend/tests/test_mvp70_api.py` (11 тестов)

1. Счета: `POST /api/accounts/sync` без дублей (повтор → 1 запись) + `GET
   /api/accounts` с `id`/`is_saved`.
2. Песочница: `TINVEST_SANDBOX=false` → все три эндпоинта 409; маппинг
   `OpenSandboxAccount`/`SandboxPayIn`/`CloseSandboxAccount` на фейковом
   клиенте (тела запросов, сумма/валюта обязательны).
3. Стратегии: создание v1, неверная конфигурация → 422 с полями, `PUT` → v2
   при неизменной v1, список версий (новые сверху), `schema` содержит
   ключевые поля, `validate` возвращает причину D1/E4.
4. Боты: создание в STOPPED, несуществующие объекты → 404/422, смена версии и
   удаление запрещены при RUNNING и при незакрытой сделке (409), разрешены в
   STOPPED без сделки.
5. Сделки: `GET deal` (нет сделки → `null`; есть → уровни, TP, стоп,
   `position_quantity`, `sl_active`), история с `close_reason` новые сверху,
   `limit`.
6. Бэктест API: успешный прогон на фейковых свечах; нет комиссий → 422;
   превышение `backtest_max_candles` → 422; нет `tick_size`/`lot_size` →
   ошибка.
7. R8: объём уровней при депозите совпадает с live-расчётом
   (`deposit_to_base_nominal` + `round_grid_to_lot`) для SIMPLE и CUSTOM;
   лоты вниз (`% 10 == 0`); SIGNAL → 422.

### Новые: `backend/tests/test_mvp70_launch.py` (3 теста)

8. `docker-compose.yml` публикует порты только на `127.0.0.1`; backend
   читает `.env` и в command есть `alembic upgrade head` + `uvicorn`;
   `.env.example` — безопасные умолчания (sandbox ON, live OFF,
   `BACKTEST_MAX_CANDLES` число). Плюс отдельная YAML-структурная проверка
   через `yaml.safe_load` в ходе валидации (см. ниже).

### Изменённые существующие тесты (из-за новых сигнатур/зависимостей)

- `tests/test_bot_lifecycle.py`: `start_bot` теперь принимает `session` и
  `broker` — обновлены 2 вызова (фейковые `_FakeSession`/`_FakeBroker`);
  `test_mutating_api_rejects_without_live_runtime` разделён: stop/emergency
  по-прежнему `(1, repo, None)`, start — новый вызов.
- `tests/test_mvp612_deal_continuation.py`: обновлён вызов `start_bot`
  (те же фейки).
- `tests/test_tinvest_api.py`: `GET /api/accounts` теперь зависит от
  `AccountService` (R2) — добавлен override-стаб и проверки `id`/`is_saved`.

### Полный набор

**557 passed, 1 skipped** (было для MVP-6.16: 535 passed + 1 skipped;
+14 новых: 11 + 3).

## Валидация

- `.venv/Scripts/python.exe -m pytest -q` → **557 passed, 1 skipped**.
- `.venv/Scripts/python.exe -m pytest tests/test_mvp70_api.py
  tests/test_mvp70_launch.py -q` → **14 passed**.
- `.venv/Scripts/python.exe -m ruff check app tests scripts` →
  **All checks passed!**
- `.venv/Scripts/python.exe -m alembic heads` → `0006_stop_loss (head)` —
  единый head (новых миграций нет).
- `npm run build` (frontend) → **✓ built in 11.37s** (фронтенд в задачу не
  входит).
- `docker compose config` — **Docker не установлен** на этой машине; вместо
  этого (допустимо заданием: «простой тест разбора YAML или проверка в
  REPORT») выполнена структурная проверка `yaml.safe_load`: все порты
  `127.0.0.1:...`, `backend.env_file` → `.env` (`required: false`), command
  содержит `alembic upgrade head` и `uvicorn`, `.env.example` — sandbox ON /
  live OFF. Реальный `docker compose up` не запускался (нет Docker) — так и
  написано.
- Diff от merge-base (`b01f8a8...d06f98a`) просмотрен: **35 файлов, +2743/
  −68**; посторонних изменений нет; Decimal/UTC, PositionManager,
  D1–D7/C1–C7/S1–S6/N1–N3/L1–L4, брокер-нейтральная архитектура и
  существующие контракты сохранены; `master` не изменялся. Новых
  Veles-семантик не вводилось: финансовые параметры (депозит бэктеста,
  комиссии, процент стопа) только обязательные, но не выдуманные.

## Соответствие AGENTS.md

- Контракт R1–R8 взят из утверждённого TASK (владелец, 2026-10-05); сверх
  R1–R8 ничего не придумано.
- Veles-семантика (индикаторы, формулы, дефолты, режимы) не изменялась;
  где официальная документация не определяет поведение — граница
  зафиксирована (стоп-заявки в песочнице: 409, без обходов; отсутствие
  `tick_size`/`lot_size`: 422; комиссии/депозит: обязательные поля).
- Брокер-нейтральность: T-Invest типы только в `TInvestAdapter`; `Decimal`/UTC.
- `master` не изменялся, force-push/rebase не применялись; публикация — после
  независимого ревью.

## Ограничения / известные границы

- **Нет авторизации** на API ⇒ все порты публикуются только на `127.0.0.1`;
  наружу сервисы недоступны (это требование R1, не обход).
- Результат бэктеста не сохраняется в БД (вне задачи).
- Бэктест синхронный (один запрос); при больших периодах упрётся в
  `backtest_max_candles`.
- В песочнице нельзя запустить бота со стоп-лоссом (нет стоп-заявок у
  T-Invest, офиц. доки) — API отвечает 409; живые контуры (боевой + токен)
  не тестировались в этой задаче (реальные вызовы T-Invest в тестах не
  делаются).
- Интерфейс (редактор стратегии, экраны ботов, форма бэктеста) — MVP-7.1;
  в 7.0 отдан машиночитаемый JSON Schema (`/api/strategies/schema`) и API.
- `---` legacy: бэктест-путь `quantity` оставлен только для существующих
  тестов (R8), новый API использует депозит.

## Публикация (AGENTS.md §6)

- Ветка реализации: `git push origin agent/review/mvp-7.0` — выполнен.
- Control: `git push origin agent/control` — выполнен (обычный push, без
  `--force`/rebase).
- Строки подтверждения:

  ```
  git ls-remote origin agent/review/mvp-7.0 agent/control
  ```

  - `d06f98a4f6258a9be7682764550d145c30da1025  refs/heads/agent/review/mvp-7.0`
    — совпадает с локальным HEAD (ветка реализации «pushed, in sync with
    origin»).
  - `refs/heads/agent/control` — подтверждён после пуша этого отчёта;
    локальный `agent/control` совпадает с `origin/agent/control`.
- `master` не изменялся; приёмку самостоятельно не объявляю.
