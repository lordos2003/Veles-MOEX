# Veles-MOEX

Веб-платформа для алгоритмической торговли инструментами MOEX через T-Invest
API, функционально сопоставимая с Veles, но адаптированная под российский рынок.

Это рабочий **modular monolith** с выделенным слоем данных (Instrument +
Market Data) и read-only интеграцией с T-Invest. Торговая логика (Strategy /
Backtest / Trading Engine) — следующие этапы, ещё не реализованы.

> Архитектурные решения и объём MVP зафиксированы в
> `Veles-MOEX — Architecture & Product Specification v1.0.md`.

## Что это за проект

- Модульный монолит, без микросервисов.
- Один будущий Strategy/Trading Engine для Live и Backtest.
- T-Invest — единственный брокер MVP; за ним следует MOEX.
- T-Invest поддерживает два предусмотренных транспорта подключения: Open API и T-Invest MCP; пользовательский выбор транспорта не создаёт второго брокера.
- Прямое подключение к MOEX (ASTS/FIX/TWIME) и Paper Trading — вне MVP.

## Уже реализовано

### Foundation

- FastAPI (Python) + Pydantic.
- React + TypeScript + Vite + Tailwind CSS.
- PostgreSQL + SQLAlchemy 2 (async) + Alembic.
- Redis (инфраструктура).
- Абстракция `BrokerAdapter`; конкретная реализация `TInvestAdapter`.

### Task №2 — T-Invest read-only integration

- Проверка авторизации/статуса подключения.
- Список счетов; портфель по счёту (cash/equity, позиции).
- Список инструментов и инструмент по FIGI.
- Последняя цена и исторические свечи.
- Нормализованные broker-agnostic DTO; типизированные ошибки.
- Торговые операции отсутствуют.

### Task №3 — Instrument & Market Data foundation

- Domain enum `InstrumentType` (SHARE/BOND/ETF/FUTURE/CURRENCY).
- Domain enum `TradingStatus`.
- Domain enum `Timeframe` (1m…1mo).
- Domain DTO `Candle` и `LastPrice` (Decimal-цены, timezone-aware UTC).
- `InstrumentService` — получение по FIGI/ticker, список, фильтры
  (type/active/ticker), синхронизация из брокера (upsert по FIGI, без дублей).
- `MarketDataService` — нормализация, чанкинг длинных диапазонов, сортировка,
  дедупликация свечей.
- PostgreSQL `MarketCandle` (уникальный ключ FIGI + timeframe + timestamp).
- Read-only REST-эндпоинты и базовая визуализация во frontend.

### Task №4 — Account / Position / Order / Deal read-only layer

- broker-agnostic DTO `BrokerAccount` (account_id, broker, статус, тип, валюты,
  cash/equity).
- broker-agnostic DTO `BrokerPosition` (account_id, FIGI, ticker, quantity,
  средняя/текущая цена, стоимость, unrealized P&L, валюта) — `Decimal`,
  timezone-aware.
- broker-agnostic DTO `BrokerOrder` (order_id, FIGI, статус, тип, направление,
  запрошенное/исполненное количество, цена, валюта, время) — read-only.
- broker-agnostic DTO `BrokerDeal` (deal_id, FIGI, направление, количество,
  цена исполнения, комиссия, валюта, время).
- `BrokerDataService` — accounts/positions/orders/deals с фильтрацией по
  account_id и FIGI; T-Invest-специфика остаётся в `TInvestAdapter`.
- Read-only эндпоинты `/api/positions`, `/api/orders`, `/api/deals`;
  нормализованные статусы/типы/направления через внутренние enum.
- Торговые операции по-прежнему не реализованы.

## Project Status

```
Task 0 — Architecture / project foundation      DONE
Task 1 — Initial skeleton                       DONE
Task 2 — T-Invest read-only integration         DONE
Task 3 — Instrument & Market Data foundation    DONE
Task 4 — Account / Position / Order / Deal read DONE
Task 5 — далее                                    NEXT
```

## Roadmap

```
DONE
├── Project architecture
├── Initial application skeleton
├── T-Invest read-only integration
├── Instrument & Market Data foundation
└── Account / Position / Order / Deal read-only layer

NEXT
└── Strategy Engine

PLANNED
├── Backtest Engine
├── DCA / Grid
├── Trading Engine
├── Risk Management
└── Live Trading
```

## Как устроено

```
Browser (React/TS)
        │
        ▼
     FastAPI
        │
        ├── Instrument Service
        │
        └── Market Data Service
                 │
                 ▼
           BrokerAdapter
                 │
          ┌──────┴──────┐
          ▼             ▼
   TInvestAdapter   TInvestMcpAdapter
     (Open API)        (MCP)
          │             │
          ▼             ▼
   T-Invest API     T-Invest MCP
          │             │
          └──────┬──────┘
                 ▼
                MOEX
```

`Strategy Engine`, `Backtest Engine` и `Trading Engine` — следующие слои
проекта. Они ещё не реализованы и должны оставаться broker-agnostic: в будущем
они обращаются к `MarketDataService`/`InstrumentService`, а не к T-Invest
напрямую.

Подробнее — `docs/architecture/README.md`.

## Структура каталогов

```
veles-moex/
├── backend/
│   ├── app/
│   │   ├── api/          # HTTP-роуты (FastAPI)
│   │   ├── core/         # конфигурация (env) и подключение к БД
│   │   ├── domain/       # broker-agnostic enum и market-data DTO
│   │   ├── models/       # SQLAlchemy ORM-модели
│   │   ├── schemas/      # Pydantic-схемы
│   │   ├── services/     # InstrumentService, MarketDataService
│   │   ├── brokers/      # BrokerAdapter + TInvestAdapter + REST-клиент
│   │   ├── strategies/   # Strategy Engine (каркас, не реализован)
│   │   ├── trading/      # Trading Engine (каркас, не реализован)
│   │   ├── backtest/     # Backtest Engine + BacktestBroker (каркас)
│   │   └── main.py       # точка входа FastAPI
│   ├── alembic/          # миграции
│   ├── tests/            # тесты
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── README.md
├── frontend/
│   ├── src/              # React + TS
│   ├── package.json
│   ├── vite.config.ts
│   └── README.md
├── docs/architecture/README.md
├── docker/               # Dockerfile'ы и nginx.conf
├── .gitignore
├── .dockerignore
├── docker-compose.yml
└── README.md
```

## Локальная разработка

Основной сценарий разработки работает **без Docker**. Нужны только Python 3.12+
и Node.js 20+.

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Проверка: `http://localhost:8000/api/health` → `{"status":"ok"}`.

Подготовить базу (нужен запущенный PostgreSQL):

```powershell
alembic upgrade head
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Открыть `http://localhost:5173`. В разработке `/api/*` проксируется в
`http://localhost:8000`.

### Тесты

```powershell
cd backend
pytest
```

### Docker (инфраструктурный вариант, не обязателен)

`docker-compose.yml` поднимает PostgreSQL, Redis, backend и frontend:

```powershell
docker compose up -d
```

## База данных

- Используется **Alembic**.
- `0001_initial` — базовая схема (основные доменные таблицы).
- `0002_instrument_fields_and_market_candles` — расширение `Instrument`
  (`trading_status`, `exchange`, NOT NULL `figi`) и таблица `market_candles`.

> Миграция `0002` закоммичена; её применение требует запущенного экземпляра
> PostgreSQL. К production/Live БД миграции не применялись.

## T-Invest

Интеграция **read-only** на текущем этапе. Архитектура предусматривает два транспорта одного брокера — Open API и T-Invest MCP; выбор транспорта должен быть скрыт за BrokerAdapter. Торговые методы остаются не реализованными до Live Trading.

Токен задаётся только в окружении backend и никогда не попадает в Git:

```powershell
$env:TINVEST_TOKEN="your_token"
```

- Токен не хранится в коде, README или frontend; реальные токены не коммитятся.
- Read-only эндпоинты:
  - `GET /api/tinvest/status`
  - `GET /api/accounts`, `GET /api/accounts/{id}`
  - `GET /api/positions`
  - `GET /api/orders`
  - `GET /api/deals`
  - `GET /api/instruments`, `GET /api/instruments/{figi}`
  - `POST /api/instruments/sync?kind=share`
  - `GET /api/market-data/{figi}/last-price`
  - `GET /api/market-data/{figi}/candles?timeframe=..&from=..&to=..`
- Единственный брокер MVP — T-Invest; прямой MOEX API, ASTS/FIX/TWIME,
  Paper Trading и микросервисы — вне MVP.
- Торговые операции (place/cancel order, deals) не реализованы.

## Тесты (текущее состояние)

- `pytest` — **47 passed**.
- `ruff check app tests scripts` — **passed**.
- `npm run build` — **passed**.

Это состояние проверено локально, а не гарантированный CI-статус. Реальный
smoke-тест T-Invest требует пользовательский `TINVEST_TOKEN` и выполняется
только локально (см. `backend/docs/tinvest-smoke-test.md`).

## Архитектурные ограничения

- T-Invest — единственный брокер MVP; Open API и MCP являются двумя транспортами одного и того же брокерского подключения.
- Пользователь выбирает транспорт T-Invest в настройках подключения; Strategy/Trading Engine не зависит от выбранного транспорта.
- Прямой MOEX API, ASTS/FIX/TWIME — вне MVP.
- Paper Trading — вне MVP.
- Микросервисы — вне MVP.
- Strategy/Backtest должны оставаться broker-agnostic.
- Стратегия является конфигурацией, а не пользовательским Python-кодом.
- Live и Backtest в будущем используют общий trading/strategy logic.
