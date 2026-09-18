# Veles-MOEX

Веб-платформа для алгоритмической торговли инструментами MOEX через T-Invest API,
функционально сопоставимая с Veles, но адаптированная под российский рынок.

Это **каркас (skeleton)** проекта: базовая инфраструктура и архитектурная основа.
Торговая логика на этом этапе не реализована.

> Архитектурные решения и объём MVP зафиксированы в
> `Veles-MOEX — Architecture & Product Specification v1.0.md`.

## Назначение

- Модульный монолит (modular monolith), без микросервисов.
- Один Strategy/Trading Engine для Live и Backtest.
- Слоистый доступ: Web UI → REST → FastAPI → Strategy/Trading → Broker →
  T-Invest API → MOEX.
- Прямое подключение к MOEX (ASTS/FIX/TWIME) и Paper Trading **вне скоупа**.
- Поддерживается один брокер (T-Invest), абстракция `BrokerAdapter` оставляет
  возможность расширения.

## Архитектура

```
Browser (React/TS)
      │ REST (/api, /api/health)
      ▼
   FastAPI (Python)
      ▼
   Strategy Engine / Trading Engine / Backtest Engine
      │                │
      │                └── Order Manager → Position Manager → Risk Manager
      ▼
   BrokerAdapter
      │
      ├── TInvestAdapter ──→ T-Invest API ──→ MOEX   (Live)
      └── BacktestBroker                         (Backtest)

Инфраструктура: PostgreSQL (данные), Redis (кэш/очередь/события), Docker.
```

Подробнее — `docs/architecture/README.md`.

## Структура каталогов

```
veles-moex/
├── backend/
│   ├── app/
│   │   ├── api/          # HTTP-роуты (FastAPI)
│   │   ├── core/         # конфигурация (env) и подключение к БД
│   │   ├── models/       # SQLAlchemy доменные ORM-модели
│   │   ├── schemas/      # Pydantic-схемы
│   │   ├── services/     # сервисы приложения (заполняется далее)
│   │   ├── brokers/      # BrokerAdapter + TInvestAdapter
│   │   ├── strategies/   # Strategy Engine (Entry / DCA-Grid / Exit)
│   │   ├── trading/      # Trading Engine (Order / Position / Risk)
│   │   ├── backtest/     # Backtest Engine + BacktestBroker
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

## Быстрый старт

### PostgreSQL и Redis

```powershell
docker compose up -d postgres redis
```

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Проверка: `http://localhost:8000/api/health` → `{"status":"ok"}`.

Применить миграции (нужен работающий PostgreSQL):

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

## Статус (рама, не торговля)

Реализовано:
- FastAPI-приложение с `/api/health`.
- Конфигурация через переменные окружения (без секретов в коде).
- ORM-модели: Instrument, Account, Order, Execution, Position, Strategy,
  StrategyVersion, Bot.
- `BrokerAdapter` (абстракция) + `TInvestAdapter` (заглушка) + `BacktestBroker`.
- Каркасы: StrategyEngine, EntryEngine, ExitEngine, DCA/Grid Engine,
  TradingEngine, OrderManager, PositionManager, RiskManager, BacktestEngine.
- PostgreSQL + Alembic (первичная миграция), Redis в `docker-compose.yml`.
- Docker-образы backend/frontend и nginx-прокси.

Не реализовано (намеренно, по следующим заданиям): реальная торговля,
T-Invest-интеграция, Backtest-исполнение, торговые стратегии, Paper Trading,
второй брокер, микросервисы.
