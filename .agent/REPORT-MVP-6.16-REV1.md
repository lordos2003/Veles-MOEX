# REPORT-MVP-6.16-REV1 — Исправления по ревью раунда 1 (B1–B3)

## Статус

**Готово к повторной проверке (раунд 2).**

- Ревью раунда 1: `.agent/REVIEW-MVP-6.16.md` (CHANGES REQUESTED: B1 —
  блокер, B2, B3; два наблюдения, реализованы).
- Реализация раунда 1 (проверенная): `e970834` (`agent/review/mvp-6.16`).
- Коммит исправлений: `a3e59e6` — "MVP-6.16 (rev1): исправления по ревью
  B1-B3" — **pushed, in sync with origin** (`git ls-remote` подтверждён в
  конце отчёта).
- База: `master @ 82254e3`; `git merge-base agent/review/mvp-6.16
  origin/master = 82254e3` (подтверждено).
- Дифф против раунда 1 (`e970834..a3e59e6`): 7 файлов, +367/−69.
- Изменений в `master` нет; публикация — только после независимого принятия.
- Issue #15 остаётся открытым до принятия и публикации.

## Что исправлено

### B1 (блокер). Исполненный стоп не виден: `GetStopOrders` без фильтра возвращает только активные

**Адаптер** (`backend/app/brokers/tinvest.py`, `app/brokers/base.py`):

- `get_stop_orders(account_id, *, from_, to)` — при заданном окне требует обе
  границы (`InvalidRequestError` иначе) и шлёт в `GetStopOrders`
  `status=STOP_ORDER_STATUS_ALL`, `from`/`to` (ISO-UTC). Без окна применяется
  поведение брокера по умолчанию (только ACTIVE). Докстринг ссылается на
  официальный контракт `StopOrdersService/GetStopOrders` (`stoporders.proto`):
  исполненные/отменённые/истёкшие возвращаются только при явном `status`
  вместе с границами `from`/`to`.
- `BrokerAdapter.get_stop_orders` (абстрактный) — сигнатура расширена тем же
  образом; бэктест-заглушка (`app/backtest/broker.py`) приведена к ней.

**DealManager** (`backend/app/trading/deal_manager.py`):

- `_broker_stops(deal)` — окно от `deal.created_at` (стоп сделки может быть
  выставлен только после открытия сделки) до `utcnow()`: история счёта целиком
  не тянется.
- `_broker_position_quantity(deal)` — позиция по FIGI **у брокера**
  (`get_open_positions`, GetPortfolio), а не только из `PositionManager`
  (0, если инструмента нет).
- `check_stop_orders` (живой путь): «заявки нет» / CANCELLED → сначала сверка
  позиции у брокера. Позиция 0 → `DealReconciliationRequired` («cannot be
  correlated to the deal (E2)») → бот ERROR, новая заявка **не выставляется**
  (проба ревьюера: вместо открытия SHORT 435 — ERROR). Реальная позиция +
  собранная сетка → переустановка ровно один раз; сетка не собрана → ERROR.
- `_recover_one` (D5): отсутствующая заявка — сначала факт TP из OrderManager;
  TP не исполнен и позиция у брокера 0 → `DealReconciliationRequired` → ERROR;
  иначе `sl_order_id = None` и ниже однократная переустановка. EXECUTED →
  закрытие `stop_loss`; UNKNOWN → ERROR.
- `_rearm_stop` больше никогда не закрывает сделку молча: нулевая
  позиция/позиция ниже целого лота/плоская позиция после отмены → явный
  `DealReconciliationRequired` (E2) с указанием причины. Добавлен guard
  «сделка уже CLOSED/CLOSING → просто выйти» — защита от D4-гонки, когда TP
  закрыл сделку, пока переустановка перечитывала позицию.

**Наблюдение 1 (лимиты T-Invest)** — реализовано: `check_stop_orders` собирает
все вооружённые сделки, вычисляет по счёту минимальный `created_at` (окно от
самой старой сделки) и делает **один** `GetStopOrders` на счёт за пачку
сообщений; ошибка чтения — бот ERROR, как раньше.

**Наблюдение 2 (silent `close_reason=None`)** — реализовано: пути нулевой и
подлотовой позиции переведены в явный ERROR с причиной (см. `_rearm_stop`).

### B2. Сбой остановки бота после стопа тихо проглатывается

`_close_deal`: исключение из `_on_stop_loss` больше не гасится — уходит в
`await self._fail_deal(deal.bot_id, deal, exc)` (существующий путь B2:
бот → ERROR, причина видна в API). Раньше бот с `stop_bot_after=true` мог
продолжить RUNNING и открыть следующую сделку.

### B3. Пустой `stopOrderId` принимается как ACTIVE

`place_stop_order`: в ответе `PostStopOrder` нет `stopOrderId`/`stop_order_id`
→ возвращается `BrokerStopOrder(order_id="", status=StopOrderStatus.UNKNOWN,
...)`. DealManager уже маппит UNKNOWN → `DealReconciliationRequired` → ERROR,
поэтому «заявка без идентификатора» больше не выглядит как ACTIVE и не
попадает в путь B1.

## Новые тесты

`backend/tests/test_mvp616_stop_loss.py`:

- `test_b1_missing_stop_with_flat_broker_position_errors` — проба ревьюера,
  порядок событий «PM ещё 435, у брокера 0»: ERROR, переустановки нет.
- `test_b1_missing_stop_with_broker_position_rearms_once` — реальная позиция
  у брокера → ровно одна переустановка.
- `test_d5_recovery_executed_stop_closes_with_stop_loss` — исполненная заявка
  при восстановлении закрывает сделку `stop_loss`.
- `test_d5_recovery_missing_stop_with_flat_broker_position_errors` —
  восстановление: заявки нет, TP не исполнен, у брокера 0 → ERROR.
- `test_d5_recovery_missing_stop_placed_once` — обновлённый фикстур (реальная
  позиция у брокера): восстановление переустанавливает один раз.
- `test_e3_stop_callback_failure_errors_bot` — сбой колбэка останова бота
  после стопа → бот ERROR (B2).

`backend/tests/test_tinvest_adapter.py`:

- `test_get_stop_orders_with_window_requests_all_statuses` — точное тело
  запроса (`status=STOP_ORDER_STATUS_ALL` + `from`/`to` в ISO-UTC).
- `test_get_stop_orders_requires_both_window_bounds` — окно без обеих границ
  → `InvalidRequestError`.
- `test_place_stop_order_without_id_returns_unknown` — ответ без
  `stopOrderId` → `UNKNOWN` (B3).

Фейковый брокер (`StopBroker.get_stop_orders`) теперь ведёт себя как
T-Invest: без `from_`/`to` возвращает только ACTIVE, с окном — все статусы
(до правок он отдавал всё всегда, из-за чего тесты не видели B1).

## Документация

`docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` §34 дополнен:

- чтение стоп-заявок: `STOP_ORDER_STATUS_ALL` + `from`/`to`-окно со ссылкой
  на официальный контракт `StopOrdersService/GetStopOrders`; размещение без
  `stopOrderId` → UNKNOWN → ERROR (B3);
- «заявки нет» — неизвестное состояние: сверка позиции у брокера перед любой
  переустановкой; позиция 0 → ERROR (E2); реальная позиция + собранная сетка
  → выставить один раз (живой путь и D5);
- сбой колбэка E3 → бот ERROR через путь B2 (причина в API).

## Валидация (backend, venv)

| Проверка | Результат |
|---|---|
| `pytest` (полный) | **543 passed, 1 skipped** (9.37s) — было 535/1 в раунде 1, +8 новых |
| `ruff check app tests scripts` | без замечаний |
| `alembic heads` | одна голова `0006_stop_loss` |

## Ограничения

- Миграции не менялись (поле `close_reason`, `sl_*` — как в раунде 1).
- `GetStopOrders` с окном запрашивает всю историю статусов счёта в
  интервале «от открытия самой старой вооружённой сделки до сейчас» — на
  длинных сделках интервал может быть большим, но ограничен сделками, а не
  всей историей счёта.
- В `_recover_one` окно от `deal.created_at` так же ограничено сделкой.

## Подтверждение

`git ls-remote origin agent/review/mvp-6.16 agent/control` (после пуша
control):

- `a3e59e68e395e10e364edb538deded3ebf2b88f8` `refs/heads/agent/review/mvp-6.16`
- `093e53bafd6a345033834264e4d0848753e7e46b` `refs/heads/agent/control`

— совпадает с локальными HEAD; пуш обычный, без `--force` и rebase.
