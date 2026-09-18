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
- `app/models` — SQLAlchemy ORM domain models
- `app/schemas` — Pydantic API schemas
- `app/services` — application services (to be filled in)
- `app/brokers` — `BrokerAdapter` abstraction + `TInvestAdapter` (stub)
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

## Database & migrations

Apply migrations (requires a running PostgreSQL):

```powershell
alembic upgrade head
```

Generate a new migration after model changes:

```powershell
alembic revision --autogenerate -m "message"
```

## Tests

```powershell
pytest
```

The tests cover backend startup, `/api/health`, configuration loading, domain
model import, broker abstraction and engine interface availability. They do not
require a running database.

## Notes

- No Paper Trading, no direct MOEX API, no ASTS/FIX/TWIME, no microservices, no
  second broker. See the product specification for the MVP roadmap.
- `TInvestAdapter` is a stub: its methods raise `NotImplementedError` until the
  T-Invest integration is implemented.
