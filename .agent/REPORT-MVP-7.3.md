# REPORT-MVP-7.3 — Первый запуск в Docker: исправления по итогам живого прогона (P1–P7) + P8 (только MOEX)

## Статус

**Реализация завершена, готово к ревью (раунд 1).**

- Ветка реализации: `agent/review/mvp-7.3` (от `master @ 55feb68`)
  - **`0409dfd`** — P1–P7 — **pushed, in sync with origin**;
  - **`687642a`** — P8 — **pushed, in sync with origin** (подтверждение
    `git ls-remote` в «Публикация»).
- База: `master @ 55feb68` (содержит принятые MVP-7.1 и MVP-7.2); `master`
  не изменялся.
- Отчёт: `agent/control:.agent/REPORT-MVP-7.3.md` — коммит в `agent/control`
  pushed.
- Самостоятельная приёмка не объявлялась — ревью за независимым ревьюером.
- P8 добавлен владельцем после первой редакции задания (Issue #23,
  2026-10-07): синхронизация справочника должна загружать только инструменты
  MOEX. Описан ниже как отдельный раздел.

## P1. `Content-Type: application/json` для запросов с телом

`frontend/src/api.ts`, `request()`: если у запроса есть `body` и заголовок
`Content-Type` не задан явно, он выставляется в `application/json`
(без дублирования — заданный вызывающим `headers["Content-Type"]`
не перетирается). Браузер больше не уходит с `text/plain`, и свежие версии
FastAPI принимают тело как JSON, а не как строку.

Новый `frontend/src/api.test.ts` (vitest, 5 тестов): `post`/`put`/`patch`
с телом реально передают `Content-Type: application/json` в `fetch`;
`get` и `post` без тела — не передают.

## P2. Воспроизводимая сборка образа — `requirements.lock`

Выбранный механизм: **constraints-файл** `backend/requirements.lock`
(43 пакета, `pip freeze` из тестового venv в состоянии, на котором
прогонялись тесты; исключена только editable-строка самого проекта).
`docker/backend.Dockerfile` ставит зависимости как
`pip install --no-cache-dir -c requirements.lock .` — сборка больше не может
незаметно подтянуть более новую версию (FastAPI и всё остальное
фиксировано; их текущие значения — fastapi 0.141.1, pydantic 2.13.5,
pydantic-settings 2.15.0, uvicorn 0.53.0, httpx 0.28.1, alembic 1.20.0,
sqlalchemy 2.0.54, redis 8.1.0 и т. д.).

Почему constraints, а не новый инструмент (pip-tools/poetry): проект
собирается через `pip install .` из `pyproject.toml`, лишний инструмент
в репозитории не нужен; constraints покрывают требование «версии совпадают
с теми, на которых прогоняются тесты». Обновлять lock нужно вместе с
`pyproject.toml` (перегенерация — `pip freeze` из venv после установки);
это указано в шапке файла.

Проверка совместимости: образ — `python:3.12-slim`, тестовый venv —
Python 3.14.6; для всех 43 пакетов в lock есть wheels под CPython 3.12
(проверено по PyPI перед фиксацией). Сборка образа backend из чистого
контекста проходит, `alembic upgrade head` внутри контейнера работает.

## P3. `CORS_ORIGINS` / `risk_blocked_instruments`: строка через запятую или JSON-массив

`backend/app/core/config.py`: поля объявлены как
`Annotated[list[str], NoDecode]` + `@field_validator(mode="before")`
`_parse_list_fields`, который принимает:

- готовый список (Python/list JSON) — как есть;
- JSON-массив (`["http://…"]`) — через `json.loads` (обязательно список,
  иначе `ValueError`);
- строку через запятую — разбивается и чистится от пробелов;
- пустую/пустую после `strip` строку — пустой список.

Это чинит падение запуска на значении `.env.example`
(`CORS_ORIGINS=http://localhost:5173` → `SettingsError` → контейнер
бэкенда не стартует) и то же для `risk_blocked_instruments` с пустым
значением в `.env`.

Тесты `backend/tests/test_config.py` (5 тестов): JSON-массив для обоих
полей, значение из `.env.example` (CORS без скобок), пустая строка для
обоих полей.

## P4. Образ доверяет корню Минцифры (цепочка `*.tbank.ru`)

Источник сертификатов: официальный портал Госуслуг
(https://www.gosuslugi.ru/crt) → прямые загрузки gu-st.ru
(`Russian_Trusted_Root_CA.cer`, `Russian_Trusted_Sub_CA.cer`,
`Russian_Trusted_Sub_CA_2024.cer`). Файлы зафиксированы в репозитории
в `docker/certs/` (формат PEM) вместе с `docker/certs/README.md`, где
указаны: источники, серийные номера и SHA-256, сверка с хранилищем
Windows, живая цепочка `invest-public-api.tbank.ru:443`
(`*.tbank.ru` → Sub CA 2024 (серийный 1005) → Root CA (серийный 1000)).

Почему файлы в репозитории, а не скачивание при сборке: сборка не
зависит от доступности и неизменности внешнего источника; содержимое
проверено (серийные номера/отпечатки совпадают с официальными и с
установленными на Windows), подлинность прослеживается по README.

`docker/backend.Dockerfile` копирует три PEM под именами `.crt` в
`/usr/local/share/ca-certificates/` и выполняет
`apt-get install ca-certificates && update-ca-certificates`.

**Важный нюанс, найденный живым прогоном:** `update-ca-certificates`
в Debian обрабатывает из `/usr/local/share/ca-certificates/` **только
файлы `*.crt`**; PEM-файлы там молча игнорируются. Первая попытка
скопировать `*.pem` как есть не дала эффекта (в контейнере снова
`self-signed certificate in certificate chain`); после копирования
под именами `.crt` — TLS-хендшейк с `invest-public-api.tbank.ru:443`
прошёл (TLSv1.3, subject `*.tbank.ru` TBank) с проверкой сертификата
**включённой**.

TLS-проверка нигде не отключается: `verify=False` и аналоги не добавлены
ни в код, ни в окружение, `SSL_CERT_FILE` не используется. Подключение
к T-Invest из контейнера работает без ручных правок — это подтверждено
живым прогоном (см. ниже, критерий 2).

## P5. Песочничные вызовы: поля REST `accountId` (по документации)

По документации T-Invest REST — это gRPC-gateway поверх proto, и поля
транскодируются из snake_case в camelCase. Источники, на которых проверены
имена полей всех трёх вызовов:

- `proto/sandbox.proto` (SandboxService) в официальном SDK:
  https://github.com/RussianInvestments/invest-api-go-sdk/blob/main/proto/sandbox.proto
- Справочник Invest API (SandboxService):
  https://tinkoff.github.io/investAPI/sandbox/

Исправления в `backend/app/brokers/tinvest.py`:

- `open_sandbox_account` — ответ содержит `accountId`: код читает
  `data.get("accountId")` (было `data.get("account_id")` → ложная ошибка
  «OpenSandboxAccount returned no account_id», хотя счёт на стороне
  T-Invest создавался);
- `sandbox_pay_in` — тело запроса `{"accountId": …}` (было `account_id`);
  ответ — `MoneyValue` с полем `balance`, парсинг
  `_quotation_to_decimal(data.get("balance"))` сохранился (поле названия
  не меняет);
- `close_sandbox_account` — тело запроса `{"accountId": …}` (было
  `account_id`); ответ пустой.

Тесты на реальных образцах REST-ответов: `backend/tests/test_tinvest_adapter.py`
(3 теста: чтение `accountId` из ответа open, тело pay-in с `accountId` +
разбор баланса, тело close с `accountId`) и `backend/tests/test_mvp70_api.py`
(маршруты песочницы на фейковом клиенте с реальными REST-формами).

## P6. Плашка успеха — отдельный стиль

`frontend/src/components/FormControls.tsx`: добавлен `SuccessBanner`
(зелёный, emerald) рядом с красным `ErrorBanner`. `SandboxPage.tsx`
показывает успех: «Пополнение выполнено, баланс: N» и
«Синхронизировано счетов: N»; сообщение сбрасывается в начале каждой
операции (создание/пополнение/закрытие счёта, синхронизация) —
устаревший успех не остаётся рядом с новой ошибкой.

## P7. Локальный запуск и документация

`README.md` (раздел «Вариант A»): шаги запуска на Windows/PowerShell уже
содержали всё требуемое (копирование `.env.example` → `.env`, вписывание
`TINVEST_TOKEN`, `TINVEST_SANDBOX=true` по умолчанию, порты только на
127.0.0.1). Добавлен абзац в шаг 3: образ бэкенда уже включает
сертификаты Минцифры, поэтому подключение к T-Invest из контейнера
работает без ручной установки сертификатов на хост и без отключения
проверки TLS (источник — `docker/certs/README.md`).

`.gitignore`: в раздел «Environment / secrets» добавлены корневой
`/certs/` (закомментировано, что привязка к корню репозитория —
`docker/certs/` остаётся в репозитории) и `docker-compose.override.yml`.

`.dockerignore`: добавлены `/certs` (корневой) и
`docker-compose.override.yml` с комментарием, что `docker/certs/`
нужен образу бэкенда и остаётся в контексте сборки; `.env` и `dist`
уже были исключены.

## P8. Синхронизация загружает только инструменты MOEX

### Признак MOEX — официальный enum `realExchange`, не поле `exchange`

По документации T-Invest поле `exchange` — свободный текст
«Торговая площадка (секция биржи)»: оно несёт значения торговых
сессий/расписаний (`moex_morning_weekend`, `moex_mrng_evng_e_wknd_dlr`,
`otc_ncc`, `SPB_RU_MORNING`, `unknown`), а **не** биржу. Надёжный признак —
официальный enum `RealExchange` (`proto/instruments.proto`, также
`common.proto`): `REAL_EXCHANGE_MOEX` («Московская биржа»),
`REAL_EXCHANGE_RTS` («Санкт-Петербургская биржа»), `REAL_EXCHANGE_OTC`,
`REAL_EXCHANGE_DEALER`, `REAL_EXCHANGE_UNSPECIFIED`. Источник —
https://github.com/RussianInvestments/invest-api-go-sdk/blob/main/proto/instruments.proto
(проверено через `gh api`, raw-файл).

Признак проверен на **живом каталоге песочницы** (1916 акций, запрос
`InstrumentsService/Shares` из контейнера бэкенда):

- `REAL_EXCHANGE_MOEX` — 270 (TQBR/MTQR, RUB/RU — Московская биржа);
- `REAL_EXCHANGE_RTS` — 1628 (SPBXM/SPBHKEX/SPBRU/SPBEQRU, в т.ч. все
  бумаги вида «CK Hutchison Holdings», HKD);
- `REAL_EXCHANGE_UNSPECIFIED` — 18 (A27, USD).

Иностранная бумага и SPB-бумага в песочнице никогда не отдают
`REAL_EXCHANGE_MOEX`, MOEX-бумага — всегда его. Фильтр построен на
verbatim-сравнении enum, без вывода «моексности» из подписи или из
`exchange`.

### Механизм

- `backend/app/brokers/base.py` — константа `REAL_EXCHANGE_MOEX`
  (с комментарием-источником) и новое поле `BrokerInstrument.real_exchange`
  (официальный enum; в PostgreSQL не сохраняется — в БД остаётся
  отображаемое `exchange`).
- `backend/app/brokers/tinvest.py` (`_to_instrument`): `real_exchange`
  берётся из `raw["realExchange"]`; отображаемое `exchange` для MOEX-бумаг
  становится `"MOEX"` вместо бессмысленного `moex_*`/`unknown`, для
  остальных сохраняется как есть.
- `backend/app/services/instruments.py` (`sync_from_broker`): фильтр
  `real_exchange == REAL_EXCHANGE_MOEX`; возвращает число
  синхронизированных MOEX-инструментов. Новый метод
  `_deactivate_missing(kind, seen)`: активные записи того же типа, которые
  брокер после фильтра не вернул (ранее загруженные иностранные/удалённые
  бумаги), помечаются `is_active = false`, **а не удаляются** — так они
  исчезают из списков выбора с `active=true` без миграции данных и без
  потери исторических ссылок (боты/бэктесты ссылаются по FIGI).
- `frontend/src/pages/OverviewPage.tsx`: выбор инструмента на «Обзоре»
  тоже запрашивает `/api/instruments?active=true` (остальные экраны уже
  фильтровали активные — BacktestPage, BotsPage, BotSettingsPanel).

### Тесты

`backend/tests/test_instrument_service.py` (3 новых):

- `test_sync_from_broker_keeps_only_moex` — образцы живого каталога:
  две MOEX-бумаги (TQBR/SBER) проходят фильтр, бумага с
  `real_exchange=REAL_EXCHANGE_RTS` (аналог CK Hutchison) не проходит
  (`synced == 2`, в БД только две);
- `test_sync_from_broker_deactivates_missing_rows` — повторная
  синхронизация без бумаги: она становится `is_active=false`, остаётся
  в БД, активный список содержит только оставшуюся;
- хелпер `_broker_instrument` по умолчанию помечает бумаги MOEX
  (существующие тесты сохраняют поведение).

`backend/tests/test_tinvest_adapter.py` (2 новых/расширенных):

- `test_get_instrument_normalized` — реальный образец MOEX-бумаги из
  песочницы (`realExchange=REAL_EXCHANGE_MOEX`,
  `exchange=moex_morning_weekend`): `exchange → "MOEX"`,
  `real_exchange` сохраняется;
- `test_to_instrument_keeps_raw_exchange_for_non_moex` — реальный образец
  иностранной бумаги (`realExchange=REAL_EXCHANGE_RTS`,
  `exchange=unknown`): метка «MOEX» не подставляется, `exchange` остаётся
  `unknown`, `is_active=false`.

## Живой прогон (критерий приёмки) — 2026-10-07, Windows/Docker Desktop

С чистого тома PostgreSQL, без ручных правок `.env` кроме токена.

**Критерий 1 — `docker compose up -d --build`.** Чистый том
(`docker compose down -v` перед стартом). Четыре контейнера — `postgres`,
`redis`, `backend`, `frontend` — в статусе `Up`/healthy; бэкенд при старте
применил миграции `alembic upgrade head` с `0001_initial` до
`0006_stop_loss` (единственный head) и поднял uvicorn;
`http://127.0.0.1:8000/api/health` → `{"status":"ok"}`.

**Критерий 2 — подключение T-Invest и справочник.** Интерфейс
`http://127.0.0.1:5173`: зелёная плашка «Подключено» (T-Invest API
connected) — TLS-хендшейк из контейнера прошёл с проверкой включённой
(см. P4). «Синхронизировать инструменты»: справочник T-Invest загружен —
инструменты появились в селекторе инструментов. На тот момент в справочнике
были и иностранные бумаги (например, «1 · CK Hutchison Holdings») — это
и есть исходный дефект, закрываемый P8 (см. «Повторный прогон P8» ниже).

**Критерий 3 — песочница и счета.** «Песочница и счета»: «+ Открыть
песочничный счёт» — карточка нового счёта появилась без ошибки
(раньше было «OpenSandboxAccount returned no account_id», P5).
Счёт открыт, позиции/заявки/сделки подгрузились (пустые). Пополнение
500000 RUB: зелёный баннер «Пополнение выполнено, баланс: 500000»
(P1/P6) — после синхронизации в таблице «Позиции» инструмент
RUB000UTSTOM, 500000 (реальный баланс пришёл из GetPortfolio).

**Критерий 4 — стратегия, бот, бэктест из интерфейса.** Из UI создана
стратегия (сохранена в БД с версией 1) и бот; записи отработали. Бэктест
запущен из UI: инструмент «1 · CK Hutchison Holdings», период
01.07.2026 10:00 → 01.08.2026 10:00, депозит 100000, комиссии
maker 0.0003 / taker 0.0003 / slippage 0.001. Результат: начальный
капитал 100000, итоговый 111465.87, чистая PnL 9870.51, ROI 0.0987,
сделок 2 (обе прибыльные, win rate 1.0, комиссии 122.92):
02.07 → 10.07 Лонг 65.3653 → 68.633565 (fixed_tp),
10.07 → 23.07 Лонг 68.8688 → 72.312240 (fixed_tp).

**Критерий 5 — воспроизводимая сборка (P2).** Образ backend собран из
чистого контекста с `-c requirements.lock`; набор версий совпадает
с тестовым venv. Пункт закрыт выбором механизма P2, повтор на второй
машине не требуется по условию.

### Наблюдения (не дефекты этого MVP)

1. На карточке счёта пишется «Баланс: 0», а реальный баланс виден в
   таблице позиций. Это документированное поведение T-Invest: список
   счетов (`UsersService/GetAccounts`) не возвращает портфель — деньги
   приходят из `GetPortfolio`. Существующее поведение UI; исправление
   (показывать баланс на карточке из GetPortfolio) — на решение владельца,
   в задачу не входит.
2. Формы требуют ручного ввода: при создании стратегии поле «ТП, %»
   появляется после выбора режима ТП; форма бэктеста явно помечает, что
   значения комиссий «не подставляются автоматически». Это существующее
   поведение форм, не менялось.
3. Методика UI-проверки: действия выполнялись в реальном браузере
   (browser-use/Playwright) по адресу `http://127.0.0.1:5173`; из-за
   ограничения среды (клики по ролевым локаторам таймаутятся) клики/ввод
   выполнялись через DOM (`evaluate`) — это те же пользовательские
   действия, на работоспособность приложения не влияет.

### Повторный прогон P8 — 2026-10-08 (критерий 2, обновлённый)

После добавления P8 образ бэкенда пересобран (`docker compose build
backend`), контейнер `backend` перезапущен, БД не очищалась — в ней
оставались 1916 инструментов от прогона 2026-10-07 (все активные), включая
иностранные («1 · CK Hutchison Holdings» — HKD).

1. `POST /api/instruments/sync?kind=share` → `{"synced": 270}` (ровно
   число `REAL_EXCHANGE_MOEX` в каталоге песочницы).
2. БД (`SELECT ... GROUP BY exchange`): активных — **270**, все со
   значением `exchange = 'MOEX'`; `unknown` (1642), `SPB_RU_MORNING` (3),
   `LSE_MORNING` (1) — `is_active = false`; «CK Hutchison Holdings»
   (currency `hkd`) — `is_active = false`, запись осталась в таблице
   (исторические ссылки не тронуты), было 1916 активных → стало 270.
3. `GET /api/instruments?active=true` → 270 записей; `exchange`:
   только `"MOEX"`; `currency`: только `RUB`; HKD-бумаг нет; SBER
   присутствует.
4. UI: список выбора «Рынок» на обзоре и остальные списки выбора
   (`?active=true`) больше не содержат иностранных бумаг; «Биржа»
   показывает «MOEX».

Иностранная бумага удалена из списков выбора без миграции данных —
за счёт деактивации, что и требовала задача («способ описать в REPORT»).

## Валидация

- `pytest` (backend, полный прогон): **591 passed, 1 skipped**.
- `ruff check app tests scripts`: **All checks passed**.
- `alembic heads`: **единственный head — `0006_stop_loss`**.
- `npm test` (frontend): **34 passed** (7 файлов).
- `npm run build`: **сборка успешна**.
- Сборка образов `docker/build backend` и `frontend`: **успешна**
  (backend — с финальным `requirements.lock` и сертификатами; см. P2/P4).

## Ограничения и замечания

- Вне задачи (не менялись): боевой режим, новые функции стратегий,
  запуск ботов на реальных заявках, формулы индикаторов, контракты
  D/C/S/N/L/E/R/U/I.
- Стек Docker от живого прогона оставлен поднятым (весь прогон велся на
  нём); остановка: `docker compose down` (данные тома сохранятся) или
  `docker compose down -v` (удалить том). Для повторного чистого прогона —
  как в критерии 1.
- Дефектов класса «первый запуск», найденных в ходе прогона и не
  входящих в P1–P7, не обнаружено; наблюдения 1–2 описаны выше.
- P8 добавлен владельцем позже (Issue #23, 2026-10-07) как расширение
  задания; реализован и проверен (см. раздел P8 и «Повторный прогон P8»).
  Признак MOEX взят из официального enum `RealExchange`; сведений
  документации/песочницы, где этот признак был бы ненадёжен, не найдено —
  граница не нарушена, «остановка на границе» не потребовалась.

## Публикация

```
git push origin agent/review/mvp-7.3      # 0409dfd (P1–P7), 687642a (P8)
git push origin agent/control             # коммит с REPORT и последующие уточнения — см. git log
git ls-remote origin agent/review/mvp-7.3 agent/control
```

**`0409dfd` (P1–P7) и `687642a` (P8) — pushed, in sync with origin**
(ветка `agent/review/mvp-7.3`). `master` не изменялся; `--force`/rebase не
применялись.
