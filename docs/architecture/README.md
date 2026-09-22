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
   ├── TInvestMcpAdapter ──→ MCP Client ──→ T-Invest MCP ──→ MOEX   (Live)
   └── BacktestBroker                                              (Backtest, та же логика)

TInvestAdapter и TInvestMcpAdapter — два транспорта одного брокера T-Invest,
а не два разных Broker. Выбранный пользователем транспорт определяется на
уровне конфигурации/фабрики и не должен просачиваться в Strategy/Backtest/Trading Engine.
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
2. **Изоляция брокера и транспорта.** Strategy/Backtest/Trading Engine не знают
   ни о T-Invest, ни о способе подключения к нему. Вся брокерская и транспортная
   специфика — внутри слоя `BrokerAdapter`. Open API и MCP являются двумя
   реализациями одного брокерского подключения.
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
| TInvestAdapter | T-Invest Open API read-only integration (Live) |
| TInvestMcpAdapter | T-Invest MCP integration boundary (Live) |
| TInvestTransport/Factory | User-selectable transport for the single T-Invest broker |
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

## T-Invest connection transport

T-Invest remains the **single broker** in MVP. The application supports two
connection transports as an architectural choice:

- **Open API** — direct T-Invest API integration used by the current `TInvestAdapter`.
- **T-Invest MCP** — MCP/HTTP Streamable integration represented by `TInvestMcpAdapter`.

The user may select the transport in the broker connection settings. The selected
transport is an implementation detail of `BrokerAdapter`; it must not change
strategy semantics, backtest behavior, position models, or order manager contracts.

The official T-Invest MCP endpoint is `https://invest-public-api.tbank.ru/mcp`.
T-Bank documents Bearer-token authentication and HTTP Streamable transport for MCP.

For the current MVP, the existing Open API adapter remains the implemented read-only
path. MCP is explicitly part of the target integration boundary and must be
implemented before the UI exposes MCP as an executable transport.

## Реализованный слой Live Execution Domain (MVP-6.1)

Broker-neutral слой исполнения (инфраструктура, не новая торговая механика):

- **ExecutionIntent** — immutable намерение выполнить действие (intent_id,
  trade_id, instrument, side, order type MARKET/LIMIT, quantity Decimal, limit
  price, reason, created_at, idempotency_key). Не зависит от протокола брокера.
- **InternalOrder** — связывает ExecutionIntent → broker order id; хранит
  requested/filled/remaining, среднюю цену исполнения, статус, reject/error.
- **Order lifecycle**: CREATED / SUBMITTED / WORKING / PARTIALLY_FILLED / FILLED /
  CANCEL_REQUESTED / CANCELLED / REJECTED / FAILED / UNKNOWN; переходы заданы
  явно (частичный fill ≠ FILLED; SUBMITTED → UNKNOWN допустимо при потере
  ответа).
- **Fill / Deal** — immutable, агрегирование нескольких fills
  (requested 100; 30+40+30 → FILLED), idempotent по fill id.
- **PositionManager** — signed quantity, weighted-average price (Decimal),
  realized/unrealized P&L, fees; позиция меняется **только** фактическими
  fills; корректно обрабатываются увеличение/уменьшение/реверс позиции.
- **OrderManager** — принимает ExecutionIntent, делает базовую валидацию,
  создаёт InternalOrder, guard идемпотентности (intent_id / idempotency_key),
  вызывает `BrokerAdapter.place_order`, хранит broker order id, обновляет
  lifecycle, принимает fills (OrderUpdate / TradeFill / PositionUpdate) и
  передаёт фактические fills в PositionManager. Не принимает стратегических
  решений.
- **Repositories** — in-memory (Intent/Order/Fill); архитектура позволяет позже
  подключить PostgreSQL без изменения domain models.
- BrokerAdapter не изменён; используется его существующая терминология
  (`place_order`, `cancel_order`, `get_order`, `get_orders`, `get_open_positions`,
  `get_deals`). T-Invest imports отсутствуют в execution domain.

## Remarks

- Direct MOEX API (ASTS/FIX/TWIME), Paper Trading, a second broker and
  microservices are out of MVP scope (see product spec sections 16–18).
- Trading methods (`place_order`, `cancel_order`, `get_order`, `get_deals`)
  remain unimplemented by design.
