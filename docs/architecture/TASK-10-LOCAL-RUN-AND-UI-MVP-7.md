# Veles-MOEX — Task 10: Local run, sandbox and strategy/bot/backtest API (MVP-7.0)

## Status

Documentation of MVP-7.0 (implemented on branch `agent/review/mvp-7.0`).
Contract R1–R8 is approved by the owner (2026-10-05) and is defined in
`.agent/TASK-MVP-7.0-LOCAL-RUN-AND-API.md` on `agent/control`.

This section mirrors the implemented REST API and launch setup. It does not
change any Veles semantics; where the official T-Invest documentation does not
define a behavior, the boundary and the limitation are stated explicitly.

---

## §1. MVP-7.0 — local run, sandbox, API

### 1.1 One-command launch (Windows / Docker Desktop)

Repository layout (root):

- `.env.example` — environment template (git-ignored `.env` is created from it);
- `docker-compose.yml` — PostgreSQL, Redis, backend, frontend;
- `README.md` → «Быстрый старт (Windows)» — PowerShell steps.

Quick start:

```powershell
Copy-Item .env.example .env      # edit TINVEST_TOKEN (sandbox token)
docker compose up --build -d
```

Points guaranteed by the compose file:

| Item | Value |
| --- | --- |
| Publish ports | all on `127.0.0.1` only (`5432`, `6379`, `8000`, `5173`) |
| Backend env | `env_file: .env` (`required: false` — app starts without it, T-Invest is `not_configured`) |
| Backend command | `sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"`; migration failure stops the container |
| Frontend | built image served on `127.0.0.1:5173` |
| Safe defaults | `.env.example`: `TINVEST_SANDBOX=true`, `LIVE_TRADING_ENABLED=false` |

Sandbox token source (official docs):
<https://tinkoff.github.io/investAPI/token/> (section «Токен песочницы»).

### 1.2 Environment variables (`.env.example`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `TINVEST_TOKEN` | empty | T-Invest API token; empty ⇒ `not_configured` |
| `TINVEST_SANDBOX` | `true` | use the T-Invest sandbox host (no real money) |
| `LIVE_TRADING_ENABLED` | `false` | live trading gate (MVP-6.5) |
| `DATABASE_URL` / `REDIS_URL` | compose-internal | container-internal addresses (compose sets them) |
| `BACKTEST_MAX_CANDLES` | `10000` | ops limit: max candles per one `POST /api/backtests` run |

### 1.3 Sandbox T-Invest: what the official documentation says

Sources (verified 2026-10-05):

- Sandbox host: `sandbox-invest-public-api.tinkoff.ru:443`
  (<https://tinkoff.github.io/investAPI/head-sandbox/>);
- Sandbox methods: <https://tinkoff.github.io/investAPI/sandbox/>;
- Difference table prod ↔ sandbox:
  <https://tinkoff.github.io/investAPI/url_difference/>.

For the paths used by Veles-MOEX:

| Capability | In sandbox | Basis |
| --- | --- | --- |
| Accounts (open/pay-in/close/list) | yes | `SandboxService`: `OpenSandboxAccount`, `SandboxPayIn`, `CloseSandboxAccount`, `GetSandboxAccounts` |
| Orders (place/cancel/status) | yes | `PostSandboxOrder`, `ReplaceSandboxOrder`, `GetSandboxOrders`, `CancelSandboxOrder`, `GetSandboxOrderState` |
| Portfolio / positions / operations | yes | `GetSandboxPortfolio`, `GetSandboxPositions`, `GetSandboxOperations` |
| Streams | yes | `PortfolioStream`, `PositionsStream`, `TradesStream` |
| **Stop orders** | **no** | no `SandboxStopOrdersService`; the docs: «В песочнице отсутствуют стоп-заявки, маржинальные показатели» |
| Margin metrics | no | same quote |
| Withdraw limits | yes (virtual) | `GetSandboxWithdrawLimits` |

**Our own live path on the sandbox host (B4, review round 1).** The difference
table states: «Используя адрес песочницы Вы можете выполнять практически те же
запросы, что и по адресу продового контура» — i.e. the *regular* services work
on the sandbox host with the same method names, which is exactly what our
adapter calls:

| Adapter call (service) | In sandbox | Basis (url_difference) |
| --- | --- | --- |
| `InstrumentsService` (instruments, shares) | yes | «Сервис инструментов — Да» |
| `UsersService.GetAccounts` | yes | «Сервис аккаунтов — Да» |
| `MarketDataService` (`GetCandles`, `GetLastPrices`, `GetTradingStatus`) | yes | «Сервис котировок — Да» |
| `OperationsService` (`GetPositions`, `GetPortfolio`, `GetOperations`, `GetWithdrawLimits`) | yes | «Сервис операций — Да» |
| `OrdersService` (`PostOrder`, `CancelOrder`, `GetOrderState`, `GetOrders`) | yes | «Сервис торговых поручений — Да» (+ `TradesStream` — Да) |
| `StopOrdersService` (`PostStopOrder`, `GetStopOrders`, `CancelStopOrder`) | **no** | «Сервис стоп-заявок — Нет» ⇒ START with stop-loss → 409 |

Known documentation gap (stated openly, owner will verify manually):
**`OrderStateStream`** (the WebSocket stream our live runtime subscribes to) is
**not in the official proto contracts** — `OrdersStreamService` exposes only
`TradesStream` (`src/docs/contracts/orders.proto`, investAPI repo), and the
difference table mentions `TradeStream` only. `OrderStateStream` is a method of
the newer T-Bank Dev Portal WS API (<https://developer.tbank.ru>), which the
difference table does not cover, so the official documentation does **not**
answer whether it works on the sandbox host. It does not block sandbox trading:
order status/executions are also available through the REST
`OrdersService.GetOrderState`, and the stream is best-effort in the sandbox.

Consequences implemented in R3:

- All `/api/sandbox/*` endpoints return **HTTP 409** when `TINVEST_SANDBOX=false`.
- A bot whose strategy config has `.exit.stop_loss` **cannot be STARTed in the
  sandbox**: the API returns **HTTP 409** with an explicit reason (no workaround,
  no silent fallback). Stop orders simply do not exist in the sandbox env.

Sandbox-specific trading behavior (documented by T-Invest): market orders fill
at the last exchange price (no market impact model), unexecuted orders are
removed after the trading session, accounts persist ~3 months after the last
use and can be deleted at any time. Consequences: after a sandbox session ends,
unfilled DCA grid limits vanish (they are not carried over to the next session
like on prod) — the sandbox is a daytime test loop, not a multi-day grid
continuation env; the average buy price is not calculated by the sandbox
operations API (FAQ 5.3) — Veles-MOEX derives the average from its own
execution records, so this does not affect it.

### 1.4 REST API (MVP-7.0 additions; broker-neutral, Decimal, UTC)

Global gateway: `http://127.0.0.1:8000` (inside Docker), OpenAPI at `/docs`.
All money fields are JSON strings (Decimal serialization). No authentication
→ **only `127.0.0.1` publishing** (see 1.5).

#### Accounts (R2)

| Method + path | Request | Response | Errors |
| --- | --- | --- | --- |
| `POST /api/accounts/sync` | empty body | `{"synced": <int>}` — number of locally tracked accounts after sync | 401 (T-Invest auth) |
| `GET /api/accounts` | — | list of `AccountInfoResponse` (broker accounts) | — |

`AccountInfoResponse` (existing + R2 additions):
`account_id`, **`id`** (local PostgreSQL id, `null` when not tracked),
**`is_saved`** (bool), `broker`, `currency`, `available_cash`, `equity`,
`currencies`, `name`, `account_type`, `status`, `opened_at`, `closed_at`,
`positions`.

Upsert rule: one row per `(broker, external_account_id)`; repeat syncs update
`name`/`is_active` and never duplicate. Deleted/absent broker accounts are not
removed locally.

#### Sandbox (R3)

Gate: every endpoint → **409** when `TINVEST_SANDBOX=false`.

| Method + path | Request | Response | Errors |
| --- | --- | --- | --- |
| `POST /api/sandbox/accounts` | empty body | `{"account_id": "<sandbox external id>"}` | 409 disabled |
| `POST /api/sandbox/accounts/{id}/pay-in` | `{"account_id": "<same id>", "amount": 50000, "currency": "RUB"}` — `amount` (Decimal, >0) and `currency` **required**, no defaults | `{"account_id", "balance"}` | 409 disabled; 409 path/body mismatch; 422 invalid amount |
| `DELETE /api/sandbox/accounts/{id}` | — | `{"account_id"}` | 409 disabled |

Open sandbox account is synchronously upserted into `accounts` (R2 rule).

#### Strategies (R4)

| Method + path | Request | Response | Errors |
| --- | --- | --- | --- |
| `POST /api/strategies` | `{name, description?, config}` | `StrategyResponse` **201** | 422 invalid `config` (field-level `loc`) |
| `GET /api/strategies` | — | `list[StrategyResponse]` (latest version) | |
| `GET /api/strategies/{id}` | — | `StrategyResponse` | 404 |
| `GET /api/strategies/{id}/versions` | — | `list[StrategyVersionResponse]` **newest first** | 404 |
| `PUT /api/strategies/{id}` | `{name?, description?, config?}` | `StrategyResponse` | 404; 422 |
| `GET /api/strategies/schema` | — | JSON Schema of `StrategyConfig` (pydantic; `title`/`description`/`enum` preserved, no new defaults) | |
| `POST /api/strategies/validate` | `{config}` | `{"valid": true, "live_deal": {"supported": bool, "reason": str \| null}}` — reason from `validate_live_deal_config()` (D1/E3/E4 scope) | 422 invalid config |

Versioning contract: create ⇒ immutable **v1**; `PUT` with a new `config` ⇒
**new** immutable version `max + 1`; old versions are never mutated (used by
bots and backtests).

#### Bots (R5/R6)

| Method + path | Request | Response | Errors |
| --- | --- | --- | --- |
| `POST /api/bots` | `{name, strategy_version_id, account_id, instrument_id, deposit?}` | `BotResponse` **201**, `status="STOPPED"` | 404 (account/instrument/version), 422 (deposit ≤ 0) |
| `PATCH /api/bots/{id}` | `{deposit?, strategy_version_id?}` (at least one key) | `BotResponse` | 409 (RUNNING or unclosed deal); 404 (bot/version); 422 (empty PATCH, null `strategy_version_id`, bad deposit) |
| `DELETE /api/bots/{id}` | — | `BotResponse` | 409 (RUNNING or unclosed deal); 404 |
| `GET /api/bots/{id}/deal` | — | `DealResponse` **or `null`** when no unclosed deal | 404 (bot) |
| `GET /api/bots/{id}/deals?limit=N` | optional `limit` ≥ 1 | `list[DealResponse]`, **newest first**, `close_reason` included | 404 (bot), 422 (limit) |
| `POST /api/bots/{id}/start` | — | `BotResponse` | 409 D1/E3/E4 risk checks; 409 strategy load; 409 stop-orders unsupported in sandbox; 503 when live disabled |
| `POST /api/bots/{id}/stop`, `/emergency-stop` | — | `BotResponse` | 409 (state), 503 |

`DealResponse` (R6 projection, source = Deal store; nothing recomputed):
`id`, `bot_id`, `instrument_figi`, `direction`, `status`, `deposit`,
`base_nominal`, `reference_price`, `lot_size`, `tick_size`, `tp_percent`,
`average_price`, **`position_quantity`** (Σ of filled level quantities),
`tp_price`, `tp_quantity`, `sl_percent`, `p0_price`, `sl_quantity`, `sl_price`,
`sl_order_id`, **`sl_active`** (`null` — no stop configured; `true` — stop
order placed; `false` — configured but disarmed), `close_reason`,
`stop_bot_after`, `levels[]` (`index`, `side`, `price`, `nominal`, `quantity`,
`offset_percent`, `status`, `is_market`, `filled_quantity`, `order_id`,
`broker_order_id`), `created_at`, `updated_at`, `closed_at`.

#### Backtests (R7/R8)

`POST /api/backtests` (synchronous; result is **not persisted**):

Request (all financial values mandatory — no defaults):

```json
{
  "strategy_version_id": 1,
  "instrument_id": 1,
  "timeframe": "1h",
  "from": "2026-01-01T00:00:00Z",
  "to": "2026-01-02T00:00:00Z",
  "deposit": 50000,
  "maker_fee": 0.0003,
  "taker_fee": 0.001,
  "slippage": 0.0005
}
```

Exactly one of `strategy_version_id` | `config`. Response: summary
(`initial_capital`, `final_capital`, `gross_pnl`, `net_pnl`, `roi`,
`total_fees`, `num_trades`, `winning_trades`, `losing_trades`, `win_rate`,
`average_trade`, `average_duration`, `max_drawdown`), `deals[]` (with
`reason`), `orders[]`, `executions[]`.

Errors: 404 (strategy version / instrument), 422 (missing fees/slippage/deposit
validation, no `tick_size`/`lot_size` on the instrument, `from ≥ to`,
candles > `backtest_max_candles`, unsupported config e.g. SIGNAL-mode live deal).

R8 contract: grid quantities are computed **by the same live sizing functions**
(`app/trading/sizing.py`, C1–C3 — `deposit_to_base_nominal`, `round_grid_to_lot`)
from the required `deposit`; the legacy `BacktestConfig.quantity` path remains
only for existing tests, the API always uses the deposit.

### 1.5 Limitations of MVP-7.0

- **No authentication** on the API ⇒ the stack publishes every port only on
  `127.0.0.1`; do not expose the container ports to the network.
- Backtest result is not saved to the DB yet; the run is synchronous (single
  request).
- Sandbox has **no stop orders** (official docs) ⇒ bots with a stop-loss in the
  config cannot start in the sandbox (409, explicit reason).
- UI (strategy editor, bot screens, backtest form) belongs to MVP-7.1; MVP-7.0
  exposes the machine-readable schema and API for it.
- `position_quantity` / `sl_active` are view projections of persisted Deal
  fields (no extra recomputation against the broker).
- Deleting a bot (`DELETE /api/bots/{id}`) keeps its history rows (`deals`,
  levels) — there is no foreign key from `deals` to `bots`, so already closed
  deals of the deleted bot remain queryable only by id in the DB and are not
  returned by the bot endpoints (the bot itself is gone). This is intentional:
  the history stays for audit purposes.
- `OrderStateStream` availability on the sandbox host is not documented by the
  official sources (see 1.3) — best-effort in the sandbox; REST
  `GetOrderState` remains the authoritative order-status source.
