# Backend

FastAPI backend for Veles-MOEX. Modular monolith, no microservices.

## Stack

- Python 3.12+
- FastAPI + Pydantic v2
- SQLAlchemy 2 (async, asyncpg) + Alembic
- PostgreSQL, Redis

## Architecture layers

- `app/api` — HTTP endpoints (FastAPI routers)
- `app/core` — configuration (env vars) and DB plumbing
- `app/domain` — broker-agnostic enums & market-data DTOs (InstrumentType,
  TradingStatus, Timeframe, Candle, LastPrice)
- `app/models` — SQLAlchemy ORM domain models
- `app/schemas` — Pydantic API schemas
- `app/services` — `InstrumentService` (persistence/sync) + `MarketDataService`
- `app/brokers` — `BrokerAdapter` abstraction + `TInvestAdapter` (read-only) +
  `TInvestError`s and a thin REST client
- `app/strategies` — Strategy Engine (Entry / DCA-Grid / Exit)
- `app/trading` — Trading Engine (Order / Position / Risk Managers)
- `app/backtest` — Backtest Engine + `BacktestBroker`

## Running locally

Create a virtual env and install:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Run the API:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `http://localhost:8000/api/health` → `{"status":"ok"}`.

## Configuration

Settings are loaded from environment variables (see `app/core/config.py`).
Copy `.env.example` to `.env` for local defaults. Never commit real secrets.

### T-Invest integration

Read-only integration with the official T-Invest API. Set the token via the
environment (never in source):

```powershell
$env:TINVEST_TOKEN="your_token"
```

Endpoints (all read-only):

- `GET /api/tinvest/status` — connection/authentication probe
- `GET /api/accounts`, `GET /api/accounts/{id}` — accounts + portfolio
- `GET /api/instruments`, `GET /api/instruments/{figi}` — instruments (from
  PostgreSQL, via the internal InstrumentService)
- `POST /api/instruments/sync?kind=share` — synchronize instruments from the
  broker into PostgreSQL (upsert by FIGI)
- `GET /api/market-data/{figi}/last-price` — last price
- `GET /api/market-data/{figi}/candles?timeframe=1d&from=...&to=...` — candles
  (normalized, sorted, de-duplicated; long ranges are fetched in chunks)

Instrument & market data are exposed through the internal services so that the
Strategy/Backtest engines never depend on T-Invest specifics. Prices use
`Decimal`, timestamps are timezone-aware UTC, and timeframe has its own internal
enum (`Timeframe`).

Errors are normalized to HTTP codes (401 auth, 429 rate limit, 400 invalid
timeframe/range, 404 not found, 502/503 upstream/connection). No trade placement
is exposed.

Smoke test (read-only, real token only if provided via env): see
`docs/tinvest-smoke-test.md` or run `python -m scripts.smoke_tinvest`.

## Database & migrations

Alembic is used for schema management:

- `0001_initial` — core domain tables.
- `0002_instrument_fields_and_market_candles` — extends `Instrument`
  (`trading_status`, `exchange`, non-null `figi`) and adds `market_candles`.

Apply migrations (requires a running PostgreSQL):

```powershell
alembic upgrade head
```

> Migration `0002` is committed; applying it requires a running PostgreSQL
> instance. It has not been applied to a live/production database.

Generate a new migration after model changes:

```powershell
alembic revision --autogenerate -m "message"
```

## Tests

```powershell
pytest
```

Current local state: **47 passed**. The tests cover backend startup,
`/api/health`, configuration loading, domain model import, broker abstraction,
engine interface availability, the T-Invest adapter + REST endpoints, and the
Instrument/MarketData services (chunking, sorting, de-duplication, sync) — all
mocked / in-memory, no real token or running database. A real T-Invest smoke
test requires a user-provided `TINVEST_TOKEN` (see `docs/tinvest-smoke-test.md`).

## Notes

- No Paper Trading, no direct MOEX API, no ASTS/FIX/TWIME, no microservices, no
  second broker. See the product specification for the MVP roadmap.
- `TInvestAdapter` implements the **read-only** integration (accounts,
  instruments, market data, candles). Trade methods (`place_order`,
  `cancel_order`, `get_order`, `get_deals`) intentionally raise
  `NotImplementedError`.
