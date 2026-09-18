# Архитектура Veles-MOEX

## Схема потока

```
Browser (React/TS, Web UI)
   │   REST
   ▼
FastAPI (Python)
   │
   ▼
Instrument Service │ Market Data Service   (внутренний слой данных)
   │                       │
   ▼                       ▼
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

Эти движки (`Strategy Engine`, `Backtest Engine`, `Trading Engine`) пока не
реализованы — существуют только архитектурные каркасы.

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
| BrokerAdapter | Abstract broker contract (read + trade) |
| TInvestAdapter | T-Invest read-only integration (Live) |
| BacktestBroker | Historical-data implementation (Backtest) |
| PostgreSQL | Persistence (instruments, market candles) |
| Redis | Cache/queue/events |

## Реализованный слой Instrument + Market Data

- Единая внутренняя модель `Instrument` (FIGI как идентификатор), внутренние
  enum `InstrumentType` / `TradingStatus`, колонка `exchange`.
- `InstrumentService` — получение по FIGI/ticker, список с фильтрами
  (type/active/ticker), синхронизация из брокера (upsert по FIGI, без дублей).
- `MarketDataService` + domain DTO `Candle` / `LastPrice` (Decimal, UTC),
  enum `Timeframe`; нормализация, сортировка, дедупликация, разбиение больших
  диапазонов на чанки.
- Роуты `/api/instruments`, `/api/market-data/*` используют внутренние сервисы;
  T-Invest остаётся только внешним источником внутри `TInvestAdapter`.

## Remarks

- Direct MOEX API (ASTS/FIX/TWIME), Paper Trading, a second broker and
  microservices are out of MVP scope (see product spec sections 16–18).
- Trading methods (`place_order`, `cancel_order`, `get_order`, `get_deals`)
  remain unimplemented by design.
