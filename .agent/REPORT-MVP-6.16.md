# REPORT-MVP-6.16 — Простой стоп-лосс в живой торговле (стоп-заявка у брокера)

## Статус

**Готово к независимому ревью.**

- Задача: `TASK-MVP-6.16-STOP-LOSS.md` (control, 2026-10-02)
- Контракт: E1–E5 (владелец, 2026-10-02)
- Ветка реализации: `agent/review/mvp-6.16` (от `master @ 82254e3`)
- Коммит: `e970834` — **pushed, in sync with origin** (`git ls-remote`
  подтверждён в конце отчёта)
- Отчёт: `agent/control:.agent/REPORT-MVP-6.16.md` — коммит в `agent/control`
  также pushed (см. строки подтверждения).

## Изменения

### 1. E1 — уровень стопа (общая формула для Live и Backtest)

- `backend/app/strategies/exit.py`: единые функции
  `simple_stop_level(reference, direction, percent)` (P0 × (1 ∓ percent/100))
  и `stop_distance_percent(first_offset, last_offset, sl_percent)`; метод
  `ExitEngine.simple_stop_decision_at_level(...)` — сравнение с известным
  уровнем стопа (порог), чтобы Backtest и Live использовали одну семантику.
- `backend/app/trading/deal.py`: `Deal.sl_price_from_p0()` — сырой уровень
  `P0 × (1 ∓ (sl_offset + sl_percent)/100)` через общую формулу;
  `align_stop_price()` — округление по тику к более раннему срабатыванию
  (LONG вверх, SHORT вниз, `round_up_to_tick`/`round_down_to_tick` D3);
  `DealStopExecuted` — стоп исполнился, пока его отмена была в полёте.
  `tick_size` отсутствует/ноль → `DealTickSizeInvalid`.
- Стоп активируется **только после исполнения всех уровней сетки**
  (E1): до этого стоп-заявки у брокера нет, `sl_order_id is None`.

### 2. E2 — стоп-заявка у брокера

- `backend/app/brokers/base.py`: брокер-нейтральные DTO
  `BrokerStopOrderRequest` / `BrokerStopOrder` (`StopOrderStatus`
  ACTIVE/EXECUTED/CANCELED/EXPIRED), enum и абстрактные методы
  `place_stop_order` / `cancel_stop_order` / `get_stop_orders`.
- `backend/app/brokers/tinvest.py`: реализация через
  `StopOrdersService` — `PostStopOrder` (тело: instrumentId, quantity в
  **лотах**, stopPrice Quotation, direction, accountId,
  expirationType `GOOD_TILL_CANCEL`, stopOrderType `STOP_LOSS`,
  orderId UUID-идемпотентность, exchangeOrderType `MARKET`),
  `CancelStopOrder` (`accountId` + `stopOrderId`), `GetStopOrders`;
  `_to_stop_order` — лоты → канонические единицы через lot_size (нет
  lot_size → `InvalidRequestError`, без тихого fallback), статус
  не-маппится → `UNKNOWN` (не угадывается). Ответ `PostStopOrder` →
  `ACTIVE` (принятая заявка GOOD_TILL_CANCEL).
- `backend/app/backtest/broker.py`: заглушки stop-методов с
  `NotImplementedError("stop orders are engine-modelled in backtest")` —
  контракт выполнен, бэктест их не использует.
- `backend/app/trading/order_manager.py`: `OrderManager.broker` (свойство),
  чтобы DealManager получал адаптер без изменения конструктора.
- `backend/app/trading/deal_manager.py` (основной объём, ~+400 строк):
  - вооружение (`_arm_stop`) → в `_after_fill`/`_grid_assembled`: после
    исполнения всех уровней выставляется одна стоп-заявка на **всю позицию**,
    округлённую вниз до целых лотов (никогда не больше позиции);
  - перевыставление в порядке E2 (как D4/B1/B3): `_stop_intent` →
    `RiskManager.check_order()` (уменьшающий ордер, исключение D7) →
    отменить старую → дождаться подтверждения (`_confirm_stop_cancelled`,
    с обработкой `DealStopExecuted`) → перечитать позицию → выставить новую
    с новым `sl_rev` (идемпотентный ключ `deal-<id>-sl-<rev>`, UUID);
    две стоп-заявки одновременно невозможны; неизвестный результат отмены
    → бот ERROR (B2 через `deactivate`/`_fail_deal`);
  - TP исполнен полностью → отменить стоп → `_close_deal(close_reason="take_profit")`;
  - стоп исполнен (`check_stop_orders`, статус EXECUTED) → отменить TP →
    `_close_deal(close_reason="stop_loss")` + колбэк `on_stop_loss(bot_id,
    stop_bot_after)`; корреляция исполнения — через `GetStopOrders` +
    сверку позиции (`БрокерскийStopOrder` по instrument + исполненному
    объёму); связать нельзя → ERROR («still reports position … ;
    reconciliation required»), без молчаливого продолжения;
  - изоляция `check_stop_orders` по B1 (exception → `_fail_deal`);
  - восстановление (D5): активная стоп-заявка **сохраняется** (если
    позиция и уровень не изменились — только тогда re-arm), исполненная →
    закрытие сделки, отсутствующая при собранной сетке → одна выставка
    после успешной сверки, UNKNOWN → ERROR;
  - B2: все ошибки жизненного цикла стопа уходят в `on_bot_error`
    (бот ERROR, причина в API).
- `backend/app/models/deal.py`, `backend/app/models/bot.py`,
  `backend/app/persistence/deal_store.py`,
  `backend/alembic/versions/0006_stop_loss.py`: поля Deal
  `sl_percent/sl_offset/p0_price/sl_rev/sl_order_id/sl_quantity/sl_price/
  close_reason/stop_bot_after` и Bot `stop_reason`; миграция `0006_stop_loss`
  (от `0005`, единый head, server_default для существующих строк).

### 3. E3 — `stop_bot_after`

- `backend/app/strategies/config.py`: `StopLossConfig.stop_bot_after:
  bool | None = None` (без выдуманного значения по умолчанию).
- `backend/app/trading/deal.py` `validate_live_deal_config()`: `None` →
  отказ при START (HTTP 409, `DealConfigUnsupported`).
- `backend/app/trading/live_execution.py` `_on_stop_loss`: `true` →
  штатная остановка MVP-6.5 (`runtime.stop()`) + персист
  `stop_reason="stop-loss"`; `false` → бот продолжает, ждёт новый FLAT-вход
  (депозит C6). Связано через `DealManager(..., on_stop_loss=...)`.
- `backend/app/models/bot.py` + `backend/app/bots/repository.py` +
  `backend/app/bots/schemas.py` + `backend/app/api/bots.py`:
  `stop_reason` в модели, `update_state(..., stop_reason=...)` и ответ API.

### 4. E4 — что разрешено в живой торговле

- `validate_live_deal_config()`: простой `stop_loss` (`kind="percent"`)
  разрешён вместе с простым TP (`fixed_percentage`) и сеткой
  SIMPLE/CUSTOM; `signal_stop`, мульти-тейк, безубыток, сигнальный TP,
  подтяжка, режим SIGNAL — по-прежнему отклоняются (тесты).

### 5. E5 — бэктест

- `backend/app/backtest/engine.py` `_evaluate_market_exit`: простой стоп
  считается по E1 — `p0 = grid_state.reference_price` (P0 = фактическая
  средняя цена исполнения первого ордера), дистанция
  `stop_distance_percent(offset[0], offset[-1], SL%)`,
  `simple_stop_level` + `simple_stop_decision_at_level` (общая функция с
  Live); активация — `_simple_stop_armed`: все уровни сетки FILLED
  (без сетки — вооружён на входе); исполнение — рыночное на следующем
  баре (как и было).

### 6. Документация

- `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` §34 «Simple stop-loss in
  live trading — MVP-6.16»: E1–E5, пример Veles (−20% от P0), миграция,
  тесты.
- `docs/architecture/TASK-08-FULL-EXIT-ENGINE-MVP-5.md` §6: добавлена
  формула уровня (P0, отступ = (последний offset − offset уровня 0) + SL%,
  LONG/SHORT, округление по тику к раннему срабатыванию, активация после
  полной сборки сетки, рыночное исполнение).

## Тесты

### Новые: `backend/tests/test_mvp616_stop_loss.py` (18 тестов)

1. Формула E1: пример Veles (перекрытие 15% + SL 5% → −20% от P0);
   «Свой» (CUSTOM 9 + 4 → −13%); из факта сделки (P0 и компонент сетки);
   LONG и SHORT; округление по тику (LONG 80.05 → 80.1, SHORT → 80.0);
   нет/ноль `tick_size` → `DealTickSizeInvalid`.
2. До полной сборки сетки стоп-заявки нет; после исполнения последнего
   уровня — одна заявка на всю позицию (435 @ 80, SELL, TP 435 @ 101.1).
3. Частичное исполнение TP → стоп перевыставлен на новый объём (335,
   rev 2, 1 CANCELLED + 1 ACTIVE); одновременно не больше одной.
4. Risk отклонил новую стоп-заявку → старая ACTIVE остаётся, бот ERROR
   («rejected by risk»), отмена не вызывалась.
5. Отмена с неизвестным результатом → бот ERROR, второй заявки нет
   (`stop_place_calls == 1`).
6. TP исполнен полностью → стоп CANCELLED, сделка CLOSED
   (`close_reason="take_profit"`).
7. Стоп сработал → TP отменён, сделка CLOSED (`close_reason="stop_loss"`),
   колбэк `(1, False)`; `stop_bot_after=true` → `(1, True)` + новый FLAT-вход;
   причина `stop-loss` персистится у бота (`BotRepository.update_state`).
8. Исполнение стопа нельзя связать (позиция осталась 435) → ERROR
   («still reports position»), бот заблокирован.
9. Восстановление D5: активная заявка не трогается (`stop_place_calls == 1`);
   отсутствующая → одна выставка (call #2, ACTIVE 435 @ 80); изменение
   позиции → re-arm; UNKNOWN → ERROR/заблокирован.
10. START: `stop_bot_after=None` → 409; `signal_stop` → 409; простой SL +
    простой TP + SIMPLE/CUSTOM → принят.

### Новые: `backend/tests/test_tinvest_adapter.py` (+8)

`PostStopOrder` (тело: instrumentId, лоты 3 из 30/лот 10, stopPrice
Quotation, direction SELL, accountId, GOOD_TILL_CANCEL, STOP_LOSS,
UUID orderId, MARKET; ответ → ACTIVE), отказ при не-кратном лоту объёме,
обязательность `account_id`, `CancelStopOrder` (тело accountId +
stopOrderId), `GetStopOrders` (нормализация: лоты → единицы, статус, side,
стоп-цена, exchangeOrderId, даты), UNSPECIFIED → `UNKNOWN`, нет lot_size →
`InvalidRequestError`.

### Новые: `backend/tests/test_exit_integration.py` (+1)

`test_stop_loss_grid_level_uses_e1_combined_offset_after_assembly`:
сетка 2 уровня, перекрытие 15%, SL 5% → стоп 80 от P0 100; до заполнения
DCA (85) срабатывания нет; заполнение на баре 2 → вооружён; бары с
закрытием 95 (нет срабатывания) → закрытие 79 ≤ 80 → выход по рынку на
следующем баре по 79, `reason == "stop_loss"`.

**Изменённых существующих тестов бэктеста нет** — поведение
`test_stop_loss_market_exit` (без сетки, вооружён на входе) сохранено;
`test_signal_tp_market_exit`, `test_deterministic_priority_protective_first`
и остальные зелёные.

## Валидация

- `./.venv/Scripts/python.exe -m pytest -q` → **535 passed, 1 skipped**
  (было для MVP-6.15: 508 + 1; +27 новых тестов: 18 + 8 + 1).
- `./.venv/Scripts/python.exe -m pytest tests/test_mvp616_stop_loss.py
  tests/test_tinvest_adapter.py tests/test_exit_integration.py -q` →
  **54 passed**.
- `./.venv/Scripts/python.exe -m ruff check app tests scripts` →
  **All checks passed!**
- `./.venv/Scripts/python.exe -m alembic heads` → `0006_stop_loss (head)` —
  единый head.
- `npm run build` (frontend) → **✓ built in 6.26s** (фронтенд не менялся,
  только поле `stop_reason` в ответе API).
- Diff от merge-base (`82254e3...e970834`) просмотрен: 20 файлов,
  +1223/−22; посторонних изменений нет; Decimal/UTC, PositionManager,
  D1–D7/C1–C7/S1–S6/N1–N3/L1–L4 и брокер-нейтральная архитектура
  сохранены; T-Invest остаётся внутри адаптера; `master` не изменялся.

## Соответствие AGENTS.md

- Контракт E1–E5 взят из утверждённого TASK (владелец); новых Veles-семантик
  не вводилось: формула уровня, порядок перевыставления, правила
  восстановления — только по контракту; где контракт ссылается на D4/B1/B3,
  использован существующий паттерн TP.
- Единственное «проектное правило» — округление стопа по тику в сторону
  более раннего срабатывания — взято из утверждённого контракта E1
  («по аналогии с D3») и зафиксировано в §34/§6.
- Отчёт на русском, код и идентификаторы — на английском (AGENTS.md §8).
- `master` не пушился; push обычные, без `--force` и rebase.

## Ограничения и пробелы спецификации

1. **Корреляция исполнения стопа**: T-Invest `PostStopOrder` возвращает
   только `stopOrderId`; исполнение рыночной заявки от стопа связывается
   через `GetStopOrders` (статус EXECUTED/собранные лоты) и сверку полного
   покрытия позиции. Если брокер не отдаёт исполнение в `GetStopOrders` или
   позиция не сходится — бот ERROR («reconciliation required»), без
   молчаливого продолжения (E2). В тестах смоделированы оба исхода.
2. **Окно опроса стопа**: `check_stop_orders` выполняется в цикле сделки
   (вместе со сверкой TP D5); отдельного WebSocket-стрима исполнений стопа
   нет — скорость закрытия зависит от частоты цикла (как и для TP).
3. **Фьючерсы**: поддержка биржевого триггерного ордера (по справке Veles)
   вне задачи — реализован рыночный стоп-ордер T-Invest
   `STOP_LOSS/MARKET`, это соответствует документированному T-Invest стопу;
   момент «нет tick_size → ошибка» для инструментов без шага цены
   (например, некоторые фьючерсные контракты) оставлен как явная ошибка по
   контракту E1.
4. **Backtest**: уровень стопа в бэктесте — P0 из `grid_state.reference_price`
   (факт исполнения первого ордера), что совпадает с Live; исполнение — на
   открытии следующего бара, как и было (E5). Для сетки `levels <= 1`
   и CUSTOM без уровней стоп вооружён сразу после входа (без сетки) —
   это зеркально общему правилу «активация после всех уровней» (их нет).
5. **`stop_bot_after=None`** допускается в конфигурации бэктеста (там нет
   START-валидации) и отклоняется только при live START (409) — граница
   соответствует E3 (запрет именно для живой торговли).

## Публикация (AGENTS.md §6)

```
git push origin agent/review/mvp-6.16        # e970834 (new branch)
git push origin agent/control                # коммит этого отчёта
git ls-remote origin agent/review/mvp-6.16 agent/control
```

## Строки подтверждения

- `git ls-remote origin agent/review/mvp-6.16` → `e970834…` (совпадает с
  локальным HEAD — ветка реализации «pushed, in sync with origin»).
- `git ls-remote origin agent/control` подтверждён после пуша этого отчёта
  (обычный push, без `--force`/rebase); локальный `agent/control`
  совпадает с `origin/agent/control`.
