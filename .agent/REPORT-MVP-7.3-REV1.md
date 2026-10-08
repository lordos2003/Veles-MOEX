# REPORT-MVP-7.3 REV1 — ответ на раунд 1: блокер B1 (TLS-доверие httpx в образе)

## Статус

**B1 исправлен, проверен в собранном контейнере и повторным живым прогоном по критерию приёмки на чистой копии. Ответ готов к раунду 2.**

- Ветка реализации: `agent/review/mvp-7.3`
  - **`5589e93`** — REV1, B1 — **pushed, in sync with origin** (подтверждение `git ls-remote` в «Публикация»);
  - `0409dfd` (P1–P7), `687642a` (P8) — без изменений.
- База: `master @ 55feb68` — `master` не изменялся.
- Дифф REV1: только `docker/backend.Dockerfile` (+9 строк). Ни одной строки Python/TypeScript не менялось — тесты и линтер предыдущих коммитов остаются в силе (`pytest`: 591 passed, 1 skipped; `ruff`: чисто; `npm test`: 34 passed; `alembic heads` — один head `0006_stop_loss`).

## B1. Механизм и обоснование

Использовано решение, ожидаемое ревьюером: `ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` (+ `SSL_CERT_DIR=/etc/ssl/certs`) в `docker/backend.Dockerfile`, сразу после блока `update-ca-certificates` (P4). Альтернативный механизм не потребовался.

Обоснование (почему именно ENV, а не что-то ещё):

1. `TInvestClient` создаёт `httpx.AsyncClient` без явного `verify` (`brokers/tinvest_client.py`), то есть httpx пользуется стандартным путём Python: `ssl.create_default_context()`.
2. `ssl.create_default_context()` в CPython читает переменные окружения `SSL_CERT_FILE` / `SSL_CERT_DIR`: если они заданы, контекст использует указанный файл вместо набора `certifi`. Это официально документированное поведение модуля `ssl`, а не обход проверки.
3. `update-ca-certificates` (P4) обновляет только системное хранилище `/etc/ssl/certs/`; certifi о нём ничего не знает — поэтому без ENV образ падал с `CERTIFICATE_VERIFY_FAILED`, хотя `openssl s_client` (системное хранилище) рукопожатие проходил. Это и была причина ложного подтверждения P4 в раунде 1: локальный `docker-compose.override.yml` с `SSL_CERT_FILE` на машине владельца маскировал дефект.
4. Значения заданы в самом образе (слой Dockerfile), а не в `docker-compose.yml` и не в `.env`: оператору ничего настраивать не нужно, «без каких-либо ручных правок .env, кроме токена» соблюдается. В `docker-compose.yml`/`.env.example` ничего не менялось.
5. **Проверка TLS не отключается**: код не трогался, `verify=False`/`ssl._create_unverified_context` нигде не вводились. Проверка в контейнере показывает `verify_mode: 2` (`CERT_REQUIRED`).

Комментарий в Dockerfile фиксирует причину (certifi vs системное хранилище) и то, что доверие направлено на системный набор, включающий корень Минцифры из P4.

## Проверка в собранном контейнере (без переменных оператора, без override)

Образ пересобран (`docker compose build backend`), стек поднят с нуля (`docker compose down -v` → `docker compose up -d --build`). В корне репозитория **нет** `certs/` и `docker-compose.override.yml`; в `docker-compose.yml` переменных `SSL_CERT_*` нет.

| Проверка | Команда | Результат |
|---|---|---|
| TLS из контейнера | `docker compose exec backend python -c "import httpx, ssl; r = httpx.get('https://invest-public-api.tbank.ru/rest'); print('status:', r.status_code); print('verify_mode:', ssl.create_default_context().verify_mode)"` | `status: 404`, `verify_mode: 2` — любой HTTP-код вместо `ConnectError` (404 — штатно для `GET /rest`), проверка включена |
| ENV в образе | `docker inspect veles_moex_backend --format '{{json .Config.Env}}'` | `"SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt"`, `"SSL_CERT_DIR=/etc/ssl/certs"` — часть образа, не окружение оператора |
| Три `.crt` в `/usr/local/share/ca-certificates/` | `ls` (P4, без изменений) | на месте; `/etc/ssl/certs/ca-certificates.crt` содержит цепочку Минцифры |

Это тот же тест из B1 (подтверждение владельца `container: 404`), выполненный теперь на образе без внешних переменных.

## Живой прогон по критерию приёмки — повторён на чистой копии

`docker compose down -v` → `docker compose up -d --build`; локальных артефактов (`certs/`, `docker-compose.override.yml`) нет, `git status` показывает только файлы реализации. Все запросы — через интерфейсный прокси (`127.0.0.1:5173`), как в реальном сценарии.

1. **Контейнеры и миграции.** Четыре контейнера подняты; `alembic heads` → `0006_stop_loss (head)`; при запуске миграции применены 0001→0006.
2. **T-Invest подключён.** `GET /api/tinvest/status` → `{"status":"connected","message":"T-Invest API connected"}` (`GET /api/health` → `{"status":"ok"}`). **Интерфейс:** карточка «T-Invest», строка «Подключено — T-Invest API connected» (снимок DOM + скриншот `gui-test-screenshots/t1_top.png`).
3. **Справочник — только MOEX (P8).** `POST /api/instruments/sync?kind=share` → `{"synced":270}`; `GET /api/instruments?active=true` → 270 записей, все `exchange:"MOEX"`, `currency:"rub"`, `is_active:true`. **Интерфейс:** селектор «Рынок» — 270 опций, все в виде «(SHARE / rub)», первая — «ABIO — Артген»; карточка выбранного инструмента: «Последняя цена: 43.9», Лот 1, Шаг цены 0.02000000, Статус TRADING_AVAILABLE, **Биржа: MOEX** (снимки DOM + скриншоты `t2_market.png`, `t3_exchange.png`).
4. **Песочница.** `POST /api/sandbox/accounts` → `21c314a5-3f09-49cb-97ec-c330d856e15c`; `POST /api/sandbox/accounts/{id}/pay-in` (500000, rub) → `{"account_id":"21c314a5-…","balance":"500000"}`. `POST /api/accounts/sync` → `{"synced":4}`. Позиции и заявки — пусто (ожидаемо).
5. **Критерий 4 (стратегия/бот/бэктест из UI) в этом прогоне повторно не выполнялся** — он зависит только от записи (`Content-Type`, P1) и не зависит от TLS-доверия (B1). REV1 меняет исключительно Dockerfile; ранее этот путь прошёл в живом прогоне раунда 1 (стратегия создана из UI → 201, открылась `/strategies/1`) и независимо подтверждён ревьюером (P1: реальный браузер, валидная форма → 201).

Скриншоты — локальные файлы `gui-test-screenshots/` (не в git): `t1_top.png` (статус «Подключено», счета), `t2_market.png` (селектор «Рынок», график, ABIO, 43.9), `t3_exchange.png` (Лот 1, Шаг цены 0.02, Статус TRADING_AVAILABLE, **Биржа MOEX**).

## Не блокирует: подтверждение замечаний раунда 1

Замечания 1–4 и наблюдение 5 приняты к сведению, для следующего MVP (в REV1 не исправлялись, чтобы не расширять объём блокера):

1. Кнопка «Проверить» в форме стратегии всегда 422 (`body.exit: Field required`) — UI шлёт `{"config":…}`, эндпоинт ждёт конфиг без обёртки; дефект с MVP-7.1, «Создать» не затрагивает.
2. 422-баннер вне полей показывает сырой JSON-список — улучшение форматирования.
3. `pydantic-settings>=2.3` → поднять до `>=2.7` (NoDecode появился в 2.7; lock держит 2.15.0).
4. Пустой ответ брокера деактивирует все активные записи типа — добавить защиту (риск низкий).
5. Карточка счёта показывает 0 (баланс «0» — наблюдение Кодера, решение владельца); деактивация не проверяет ссылки активных ботов.

## Публикация

```
git push origin agent/review/mvp-7.3      # 5589e93 (REV1, B1)
git push origin agent/control             # этот отчёт + статус задачи
git ls-remote origin agent/review/mvp-7.3 agent/control
```

**`5589e93` — pushed, in sync with origin** (ветка `agent/review/mvp-7.3`, remote SHA == локальному `5589e935756ded978d1fe48fcf862fdb40749204`). `master` не изменялся; `--force`/rebase не применялись.
