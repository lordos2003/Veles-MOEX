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
фильтров/сигналов и входа; `Backtest Engine`, `Trading Engine` и исполнение
ордеров (`place_order` и т.п.) пока не реализованы.

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

## Remarks

- Direct MOEX API (ASTS/FIX/TWIME), Paper Trading, a second broker and
  microservices are out of MVP scope (see product spec sections 16–18).
- Trading methods (`place_order`, `cancel_order`, `get_order`, `get_deals`)
  remain unimplemented by design.
