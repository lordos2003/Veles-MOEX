# REPORT-MVP-7.0-REV1 — Исправления по ревью раунда 1 (B1–B4)

## Статус

**Готово к повторному ревью (раунд 2).**

- Ревью раунда 1: `.agent/REVIEW-MVP-7.0.md` (Claude, 2026-10-05) —
  **CHANGES REQUESTED**: B1–B4 (обязательные) + 2 пункта «по желанию».
- Ветка реализации: `agent/review/mvp-7.0`
  - раунд 1: `d06f98a` (pushed, in sync with origin);
  - раунд 2: **`76cba1e`** — **pushed, in sync with origin** (подтверждение
    `git ls-remote` в конце отчёта).
- База: `master @ b01f8a8`; `master` не изменялся.
- Отчёт: `agent/control:.agent/REPORT-MVP-7.0-REV1.md` — коммит в
  `agent/control` pushed.

## B1 — капитал бэктеста = депозит

`backend/app/api/backtests.py`: при сборке `BacktestConfig` теперь передаётся
`initial_capital=payload.deposit` (R8-путь всегда депозитный). Раньше
`initial_capital` брал предустановленное `Decimal("10000")`, из-за чего
`initial_capital`/`final_capital`/`roi` в ответе считались от выдуманного
капитала 10 000. Теперь, при депозите 50 000 и прибыли 5 000, ROI = 10%,
а не 50%.

Тест: `test_backtest_initial_capital_is_deposit` — при депозите 50 000:
`initial_capital == 50000`, `final_capital == initial + net_pnl`,
`roi == net_pnl / initial`.

## B2 — предел свечей оценивается до запросов к брокеру

`backend/app/api/backtests.py`: перед `market_data.get_candles` добавлена
оценка числа свечей по календарю (`_estimate_candle_count`: длина периода в
секундах / длительность таймфрейма, +1). Если оценка > `backtest_max_candles` →
**422** сразу, без обращений к брокеру. Проверка по фактически загруженному
числу свечей **остаётся** как авторитетная (страховка на случай, когда
календарная оценка занижает/завышает).

`backend/app/services/market_data.py`: добавлена публичная
`timeframe_seconds(timeframe)` (календарная длительность таймфрейма;
используется и для оценки).

Тест: `test_backtest_candle_precheck_before_broker` — период в 2 года на `1m`
→ 422 с «backtest_max_candles», и `MarketDataService.get_candles` **не
вызывается** (счётчик вызовов = 0).

Ограничение (документировано): оценка — календарная, верхняя граница; на
границе лимита запрос, формально превышающий оценку, но фактически
умещающийся (короткая торговая сессия), будет отклонён — владелец просто
сокращает период. Авторитетная проверка осталась после загрузки.

## B3 — таймфрейм запроса vs таймфрейм стратегии

`backend/app/api/backtests.py`: если у `StrategyConfig.timeframe` задан и он
не равен `timeframe` запроса → **422** (до загрузки свечей): «strategy
timeframe 1h does not match the request timeframe 5m». Если в стратегии
таймфрейм не задан — используется таймфрейм запроса (он обязателен в
запросе, как и было).

Тест: `test_backtest_strategy_timeframe_must_match` — `1h` в стратегии против
`5m` в запросе → 422 с упоминанием таймфреймов; совпадение (`5m`/`5m`) → 200.

## B4 — наш путь на хосте песочницы (исследование, без кода)

Проверено по официальной документации T-Invest (2026-10-05):

- Таблица различий прод/песочница: **`https://tinkoff.github.io/investAPI/url_difference/`**:
  «Используя адрес песочницы Вы можете выполнять практически те же запросы,
  что и по адресу продового контура».

| Вызов нашего адаптера | Песочница | Основание (url_difference) |
| --- | --- | --- |
| `InstrumentsService` (инструменты) | Да | «Сервис инструментов — Да» |
| `UsersService.GetAccounts` | Да | «Сервис аккаунтов — Да» |
| `MarketDataService.GetCandles / GetLastPrices / GetTradingStatus` | Да | «Сервис котировок — Да» |
| `OperationsService.GetPositions / GetPortfolio / GetOperations` | Да | «Сервис операций — Да» |
| `OrdersService.PostOrder / CancelOrder / GetOrderState / GetOrders` | Да | «Сервис торговых поручений — Да» |
| `StopOrdersService.PostStopOrder / GetStopOrders / CancelStopOrder` | **Нет** | «Сервис стоп-заявок — Нет» |

- Дополнительно `https://tinkoff.github.io/investAPI/head-sandbox/`: методы
  работы с поручениями в песочнице «аналогичны» боевым; рыночные заявки
  исполняются по `last_price`; **все неисполненные поручения удаляются после
  окончания торговой сессии** (для нашей DCA-сетки в песочнице это значит:
  неисполненные лимитки не переносятся на следующую сессию, как на проде);
  счета хранятся 3 мес., могут быть удалены в любой момент; «В песочнице
  отсутствуют стоп-заявки, маржинальные показатели»; средняя цена покупки
  песочницей не рассчитывается (FAQ 5.3) — у нас она выводится из собственных
  исполнений, поэтому не влияет.

**Известный пробел документации (указан честно, владелец проверит вручную):**
`OrderStateStream` — поток, на который подписывается наш live-рантайм, — в
официальном proto-контракте отсутствует: `OrdersStreamService` содержит только
`TradesStream` (`src/docs/contracts/orders.proto`, репозиторий Tinkoff/investAPI
— проверено по исходникам). В таблице различий упомянут только `TradeStream`
(Да). `OrderStateStream` — метод потокового API T-Bank Dev Portal
(`developer.tbank.ru`; на этой машине портал недоступен — TLS-ошибка), и
официальная таблица различий про него ничего не говорит. **Вывод: документация
не подтверждает и не опровергает работу `OrderStateStream` на хосте
песочницы.** Это НЕ блокирует песочницу: статусы/исполнения доступны через
REST `OrdersService.GetOrderState`, стрим в песочнице — best-effort
(внутренняя логика переподключения уже есть).

**Вывод по B4: гейт 409 при START в песочнице остаётся только для ботов со
стоп-лоссом** (StopOrdersService в песочнице нет). Весь остальной путь (заявки,
тайм-статус, позиции, портфель) на хосте песочницы, согласно официальной
таблице различий, поддерживается. Дополнительный код не требовался; ответ
зафиксирован в `docs/architecture/TASK-10-LOCAL-RUN-AND-UI-MVP-7.md` §1.3.

## Мелочи (по желанию — сделаны)

- `StopLossConfig.percent`: описание в схеме исправлено с «Stop-loss percent
  from reference» на **«Stop-loss percent from P0, above the grid overlap»**
  (E1: SL% сверх перекрытия сетки от P0). Значение/семантика не изменились —
  только текст подписи (для формы MVP-7.1).
- Удаление бота оставляет закрытые сделки в `deals` (внешнего ключа нет) —
  добавлено в §1.5 документации TASK-10 как намеренное поведение (история
  остаётся для аудита; после удаления бота его история по эндпоинтам ботов не
  отдаётся).

## Документация

- `docs/architecture/TASK-10-LOCAL-RUN-AND-UI-MVP-7.md` §1.3 — добавлена
  таблица «наш путь на хосте песочницы» (по вызовам адаптера, со ссылкой на
  url_difference), зафиксирован пробел про `OrderStateStream`, поведение
  песочницы (заявки после сессии, 3 мес., средняя цена).
- Там же §1.5 — удаление бота и история; `OrderStateStream` best-effort.

## Тесты

Новые (в `backend/tests/test_mvp70_api.py`, 3):

1. `test_backtest_initial_capital_is_deposit` (B1);
2. `test_backtest_candle_precheck_before_broker` (B2, брокер не вызван);
3. `test_backtest_strategy_timeframe_must_match` (B3, 422 + 200 при совпадении).

Существующие тесты не менялись (проверка лимита свечей в
`test_backtest_candle_cap_and_instrument_facts` теперь срабатывает на
пре-проверке — ассерты те же, 422 + «backtest_max_candles»).

## Валидация

- `.venv/Scripts/python.exe -m pytest -q` → **560 passed, 1 skipped**
  (было 557/1; +3 новых).
- `.venv/Scripts/python.exe -m ruff check app tests scripts` → **All checks
  passed!**
- `.venv/Scripts/python.exe -m alembic heads` → `0006_stop_loss (head)` —
  единый head, новых миграций нет.
- Фронтенд не изменялся (npm build не требуется; для информированности
  прогон не делался — изменений JS/TS нет в этом диффе).
- Diff от `d06f98a...76cba1e`: 5 файлов, +184/−4 (backtests.py,
  market_data.py, strategies/config.py, test_mvp70_api.py, TASK-10 doc) —
  просмотрен; посторонних изменений нет. Veles-семантика не менялась
  (B3 — проверка согласованности, не новая семантика; B1 — привязка к
  существующему параметру депозита; B2 — лимит из существующей настройки).

## Известные ограничения (без изменений по сравнению с раундом 1)

- Нет авторизации → порты только `127.0.0.1`.
- Результат бэктеста не сохраняется; запуск синхронный.
- Стоп-заявок в песочнице нет → 409 (см. B4; дополнительных 409 не требуется).
- `docker compose up` реально не запускался (Docker на машине отсутствует);
  YAML-структурная проверка и regex-тесты `test_mvp70_launch.py` — как в
  раунде 1.
- `OrderStateStream` на хосте песочницы — документально не подтверждён
  (владелец проверит вручную).

## Публикация (AGENTS.md §6)

- Ветка реализации: `git push origin agent/review/mvp-7.0` → `76cba1e`
  (обычный push, без `--force`/rebase).
- Control: `git push origin agent/control` — выполнен.
- Строки подтверждения:

  ```
  git ls-remote origin agent/review/mvp-7.0 agent/control
  ```

  - `refs/heads/agent/review/mvp-7.0` → `76cba1e…` — совпадает с локальным
    HEAD, «pushed, in sync with origin».
  - `refs/heads/agent/control` — подтверждён после пуша этого отчёта;
    локальный `agent/control` совпадает с `origin/agent/control`.
- `master` не изменялся; приёмку самостоятельно не объявляю.
