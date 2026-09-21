# Архитектура Veles-MOEX

## Схема потока

```
Browser (React/TS, Web UI)
   │   REST
   ▼
FastAPI (Python)
   │
   ├── Instrument Service
   ├── Market Data Service
   └── Broker Data Service   (accounts / positions / orders / deals)
   │
   ▼
BrokerAdapter (абстракция)
   │
   ├── TInvestAdapter ──→ TInvestClient ──→ T-Invest API ──→ MOEX   (Live)
   └── BacktestBroker                                              (Backtest, та же логика)
```

В будущем:

```
Strategy Engine ──→ Market Data Service
Backtest Engine ──→ Historical Market Data
```

`Strategy Engine` (MVP-2) реализован как конфигурационно-управляемый движок
фильтров/сигналов и входа. `Backtest Engine` (MVP-3) использует тот же
Strategy Engine и исполняет сделки через `BacktestBroker`. `Trading Engine`
(Live) и исполнение ордеров (`place_order` у T-Invest) пока не реализованы.

## Принципы

1. **Один движок.** Live и Backtest используют один и тот же
   Strategy/Trading Engine; отличаются только адаптеры исполнения
   (`TInvestAdapter` vs `BacktestBroker`).
2. **Изоляция брокера.** Strategy Engine не знает о T-Invest. Вся
   брокерская специфика — внутри слоя `BrokerAdapter`.
3. **Стратегия — это данные.** Стратегия описывается конфигурацией (например,
   условиями входа, сеткой DCA, типами тейк-профита), а не пользовательским
   Python-кодом.
4. **Версии стратегий неизменяемы.** `StrategyVersion` — отдельная сущность;
   исторический бэктест ссылается на конкретную версию, что обеспечивает
   воспроизводимость.
5. **Risk Manager над стратегией.** Стратегия не может обойти Risk Manager.

## Слои

| Layer | Responsibility |
|------|-----------------|
| Browser | Web UI, display, strategy input |
| FastAPI | REST/WebSocket, validation, routing |
| Instrument Service | Instruments from PostgreSQL (filters, sync-by-FIGI upsert) |
| Market Data Service | Normalized last price / candles, chunking, sort, de-duplication |
| Broker Data Service | Accounts / positions / orders / deals (read-only, filtering) |
| BrokerAdapter | Abstract broker contract (read + trade) |
| TInvestAdapter | T-Invest read-only integration (Live) |
| BacktestBroker | Historical-data implementation (Backtest) |
| PostgreSQL | Persistence (instruments, market candles) |
| Redis | Cache/queue/events |

## Реализованный слой Instrument + Market Data + Broker Data

- Единая внутренняя модель `Instrument` (FIGI как идентификатор), внутренние
  enum `InstrumentType` / `TradingStatus`, колонка `exchange`.
- `InstrumentService` — получение по FIGI/ticker, список с фильтрами
  (type/active/ticker), синхронизация из брокера (upsert по FIGI, без дублей).
- `MarketDataService` + domain DTO `Candle` / `LastPrice` (Decimal, UTC),
  enum `Timeframe`; нормализация, сортировка, дедупликация, разбиение больших
  диапазонов на чанки.
- `BrokerDataService` — read-only слой `Account` / `Position` / `Order` /
  `Deal` с broker-agnostic DTO (Decimal, UTC) и фильтрацией по account_id/FIGI.
- Роуты `/api/instruments`, `/api/market-data/*`, `/api/positions`,
  `/api/orders`, `/api/deals` используют внутренние сервисы; T-Invest
  остаётся только внешним источником внутри `TInvestAdapter`.

## Реализованный слой Strategy Engine (MVP-2)

Стратегия — это данные (Veles-модель), движок broker-agnostic:

- `Strategy` / `StrategyVersion` и `Instrument` — существующие сущности;
  `Direction` (Long/Short) в конфигурации.
- **Filters / Signals** по модели Veles: `Аргумент1 + Оператор + Аргумент2`;
  аргумент — индикатор, свеча (open/high/low/close/volume) или константа.
- Операторы: `>` / `<` (состояние, активно пока условие выполняется),
  `crossing upward` / `crossing downward` (событие пересечения).
- Группы: условия внутри группы = AND, группы между собой = OR
  (поддерживается вложенность `(A AND B) OR C`).
- Методы расчёта: `at_bar_close` (по закрытой свече) и `per_minute`
  (внутри текущей формирующейся свечи).
- Каждый аргумент несёт свой `timeframe`; higher-timeframe сигнал остаётся
  активным до конца свечи и сочетается с lower-timeframe условием
  (multi-timeframe active signal).
- Индикаторы: RSI, SMA, EMA, MACD, Bollinger Bands, ATR, CCI, Williams %R,
  CMO, MFI, Stochastic, ADX; конфигурация period / method / shift / серия
  вывода (MACD histogram, BB upper/lower, Stochastic k/d, ADX +/-DI).
- **Entry Engine** формирует `EntrySignal` (Long→BUY, Short→SELL),
  не отправляет ордера.
- **Basic Exit**: только `FixedPercentageTP` (единственный тейк-профит
  от цены входа). DCA/Grid, Multi-Take, Signal TP, Break-Even, Stop Loss,
  Trailing — последующие этапы.

## Реализованный слой Backtest Engine (MVP-3)

- `BacktestBroker` — broker-agnostic интерфейс исполнения поверх исторических
  свечей: market/limit ордера, отмена, состояния ордера (NEW/SUBMITTED/
  FILLED/CANCELLED), заполнения, баланс счёта, позиция. Детерминированные
  правила заполнения (market по цене/слайпеджу, limit по OHLC-правилу).
- Комиссии (maker/taker) и slippage — часть конфигурации; попадают в
  исполнение, сделку, realized и Net P&L (Gross P&L без комиссии).
- Позиция: quantity, average_price, unrealized/realized P&L, fees, opened_at/
  closed_at; средняя цена пересчитывается при увеличении позиции (совместимо
  с будущим DCA).
- Тайминг Veles: только `at_bar_close`; сигнал на закрытии свечи N
  исполняется на OPEN свечи N+1; `per_minute` в backtest не поддерживается;
  look-ahead исключён (данные старше текущей свечи).
- Выход: `FixedPercentageTP` от текущей средней цены; полное закрытие одной
  сделкой. Multi-Take / Signal TP / Break-Even / Stop Loss / Trailing — нет.
- Воспроизводимая история `Backtest → Deals → Orders → Executions`, а также
  `BacktestResult`: initial/final capital, gross/net P&L, ROI, total fees,
  number of closed trades, winning/losing, win rate, average trade/duration,
  maximum drawdown. Backtest ссылается на конкретную `StrategyVersion` и
  полностью детерминирован по конфигурации.
- `BacktestBroker`/`BacktestEngine` и `Strategy Engine` не импортируют
  `brokers/tinvest`/`TInvestAdapter`.

## Реализованный слой DCA / Grid (MVP-4)

Veles-совместимый DCA/Grid движок, broker-agnostic:

- **TradingMode**: `SIMPLE` / `CUSTOM` / `SIGNAL`; `Direction` Long/Short.
- **SIMPLE**: Перекрытие изменения цены (диапазон между первым и последним
  ордером сетки), Сетка ордеров (число уровней, первый ордер — часть сетки),
  Отступ первого ордера (Long ниже, Short выше; 0 = market), фиксированное
  распределение, % Мартингейла (номинал каждого следующего ордера =
  предыдущий × (1 + percent/100), считается в валюте, не в количестве),
  логарифмическое распределение (коэффициент 1 = линейно, >1 плотнее у цены
  входа, <1 плотнее к дальнему краю), частичное выставление (active limit),
  подтяжка сетки (pull-up; игнорируется для market-первого ордера).
- **CUSTOM**: явный список уровней (offset + nominal %), валидация монотонности
  офсетов и положительности номинала; одиночный ордер 100% — валиден.
- **SIGNAL**: первый ордер market при offset=0, limit при offset>0; последующие
  усреднения — market, требуют сигнал + минимальный офсет (от предыдущего
  ордера или от reference). Переиспользуются Filters/Signals из Task №5.
- Доменные модели: `GridLevel`, `GridOrderPlan`, `DCAOrder`, `GridState`; матем.
  маппинг цен изолирован в `GridPriceDistribution`.
- Средняя цена пересчитывается взвешенно: `sum(quantity_i*price_i)/sum(quantity_i)`;
  после каждого DCA состояние сетки обновляется (выполненный уровень
  неизменяем, следующий ожидающий становится активным), средняя цена —
  авторитетная база для тейк-профита (полный Exit Engine — позже).
- **Backtest-интеграция**: SIMPLE/CUSTOM сетка исполняется лимитными DCA-ордерами
  по существующему детерминированному OHLC-правилу; позиция усредняется,
  TP перевыставляется от новой средней цены. SIGNAL-усреднения реализованы на
  уровне движка (market DCA по сигналу в bar-loop не моделируется).
- Не реализовано (следующие этапы): Trailing, live trading, Order recovery,
  Risk Manager, optimizer, partial fills, tick engine.

## Реализованный слой Full Exit Engine (MVP-5)

Veles-совместимый полноценный Exit Engine, broker-agnostic (единый для Backtest
и Live):

- **Fixed TP / Простой**: один лимитный тейк-профит от средней цены позиции
  (Long выше, Short ниже); после DCA старый TP отменяется и пересоздаётся от
  новой средней цены на оставшийся объём.
- **Multi-Take / Свой**: последовательность частичных выходов (offset + % объёма
  от позиции), лимитные ордера, монотонно возрастающие офсеты, сумма объёмов
  ≤ 100%; после DCA оставшиеся тейки пересчитываются от новой средней цены,
  выполненные остаются неизменными.
- **Signal TP / Сигнал**: market-выход по Veles Filters/Signals (Task №5),
  с гейтом **Minimum P&L**.
- **Break-Even Protection** («стоп-лосс в безубыток», НЕ обычный SL): доступен
  с Multi-Take (≥ 2 тейков), активируется после первого тейка (отменяет
  DCA/Grid), опорная точка — средняя цена или предыдущий тейк, отклонение
  положительное/нулевое/отрицательное.
- **Simple Stop Loss** (перцент) и **Signal Stop Loss** (сигнал + min offset от
  средней цены или последнего ордера, положительный offset допускается) —
  независимые market-выходы; срабатывает первый.
- Доменные модели: `ExitMode`, `ExitDecision`, `ExitState`; детерминированная
  приоритезация одновременных условий в Backtest; `BacktestDeal` несёт `reason`
  (fixed_tp / take / signal_tp / breakeven / stop_loss / signal_stop).
- Переиспользуются Filters/Signals (Task №5), Backtest (Task №6), DCA/Grid
  (Task №7), Position и BacktestBroker. Второй системы индикаторов/сигналов/
  позиций не создано.
- Не реализовано: Trailing, partial fills, tick engine, live trading.

## Remarks

- Direct MOEX API (ASTS/FIX/TWIME), Paper Trading, a second broker and
  microservices are out of MVP scope (see product spec sections 16–18).
- Trading methods (`place_order`, `cancel_order`, `get_order`, `get_deals`)
  remain unimplemented by design.
