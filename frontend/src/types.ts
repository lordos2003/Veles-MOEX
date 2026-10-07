/**
 * API types mirroring the FastAPI response/request schemas
 * (backend/app/schemas/*, app/bots/schemas.py, app/backtest/schemas.py).
 * Values are kept as returned by the API (strings for Decimal prices).
 */

// --- runtime (U2) ---
export interface RuntimeResponse {
  sandbox: boolean;
  live_trading_enabled: boolean;
  tinvest_configured: boolean;
}

// --- health / T-Invest status ---
export interface HealthResponse {
  status: string;
}

export interface TInvestStatus {
  status: "connected" | "not_configured" | "error";
  message: string;
}

// --- strategies / indicators (U3, U4) ---
export type IndicatorParamType = "int" | "float";

export interface IndicatorParamDef {
  name: string;
  type: IndicatorParamType;
  required?: boolean;
}

export interface IndicatorResponse {
  name: string;
  series: string[];
  uses_period: boolean;
  uses_method: boolean;
  uses_series: boolean;
  uses_params: boolean;
  params: IndicatorParamDef[];
}

/** Raw pydantic JSON Schema node (subset used by the form builder). */
export interface SchemaNode {
  $ref?: string;
  type?: string;
  properties?: Record<string, SchemaNode>;
  required?: string[];
  items?: SchemaNode;
  enum?: unknown[];
  const?: unknown;
  default?: unknown;
  anyOf?: SchemaNode[];
  oneOf?: SchemaNode[];
  discriminator?: { propertyName?: string; mapping?: Record<string, string> };
  title?: string;
  description?: string;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
}

export interface StrategyResponse {
  id: number;
  name: string;
  description: string | null;
  is_active: boolean;
  config: Record<string, unknown>;
  versions: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface StrategyVersionResponse {
  id: number;
  strategy_id: number;
  version: number;
  config: Record<string, unknown>;
  created_at: string;
}

export interface StrategyCreateRequest {
  name: string;
  description?: string | null;
  config: Record<string, unknown>;
}

export interface StrategyUpdateRequest {
  name?: string | null;
  description?: string | null;
  config?: Record<string, unknown>;
}

export interface StrategyValidateResponse {
  valid: boolean;
  live_deal: { supported: boolean; reason: string | null };
}

// --- bots (U5) ---
export type BotStatus =
  | "STOPPED"
  | "STARTING"
  | "RUNNING"
  | "STOP_REQUESTED"
  | "EMERGENCY_STOP"
  | "ERROR";

export interface BotResponse {
  id: number;
  name: string;
  status: BotStatus;
  strategy_version_id: number | null;
  account_id: number | null;
  instrument_id: number | null;
  deposit: string | null;
  started_at: string | null;
  stopped_at: string | null;
  stop_reason: string | null;
  deal_error: string | null;
  last_error: string | null;
  last_skip_reason: string | null;
}

export interface BotCreateRequest {
  name: string;
  strategy_version_id: number;
  account_id: number;
  instrument_id: number;
  deposit: string | null;
}

export interface BotUpdateRequest {
  deposit?: string | null;
  strategy_version_id?: number | null;
}

export interface StrategyVersionOption {
  id: number;
  version: number;
  created_at: string;
}

export interface DealLevelResponse {
  index: number;
  side: string;
  price: string | null;
  nominal: string;
  quantity: string;
  offset_percent: number;
  status: string;
  is_market: boolean;
  filled_quantity: string;
  order_id: string | null;
  broker_order_id: string | null;
}

export interface DealResponse {
  id: number;
  bot_id: number | null;
  instrument_figi: string;
  direction: string;
  status: string;
  deposit: string | null;
  base_nominal: string;
  reference_price: string;
  lot_size: number | null;
  tick_size: string | null;
  tp_percent: number;
  average_price: string;
  position_quantity: string;
  tp_price: string | null;
  tp_quantity: string | null;
  sl_percent: number | null;
  p0_price: string | null;
  sl_quantity: string | null;
  sl_price: string | null;
  sl_order_id: string | null;
  sl_active: boolean | null;
  close_reason: string | null;
  stop_bot_after: boolean | null;
  levels: DealLevelResponse[];
  created_at: string | null;
  updated_at: string | null;
  closed_at: string | null;
}

// --- backtest (U6) ---
export interface BacktestRequest {
  strategy_version_id?: number | null;
  config?: Record<string, unknown> | null;
  instrument_id: number;
  timeframe: string;
  from: string;
  to: string;
  deposit: string;
  maker_fee: string;
  taker_fee: string;
  slippage: string;
}

export interface BacktestDealResponse {
  deal_id: string;
  direction: string;
  entry_time: string;
  exit_time: string;
  entry_price: string;
  exit_price: string;
  quantity: string;
  gross_pnl: string;
  fees: string;
  net_pnl: string;
  duration_seconds: number;
  executed_orders: number;
  reason: string;
}

export interface BacktestExecutionResponse {
  deal_id: string;
  instrument_figi: string;
  side: string;
  quantity: string;
  price: string;
  account_id: string | null;
  order_id: string | null;
  commission: string;
  currency: string | null;
  happened_at: string | null;
}

export interface BacktestOrderResponse {
  order_id: string;
  status: string;
  account_id: string | null;
  instrument_figi: string | null;
  type: string | null;
  side: string | null;
  requested_quantity: string;
  executed_quantity: string;
  price: string | null;
  executed_average_price: string | null;
  currency: string | null;
  created_at: string | null;
  updated_at: string | null;
  reject_info: string | null;
}

export interface BacktestResponse {
  initial_capital: string;
  final_capital: string;
  gross_pnl: string;
  net_pnl: string;
  roi: string;
  total_fees: string;
  num_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: string;
  average_trade: string;
  average_duration: string;
  max_drawdown: string;
  deals: BacktestDealResponse[];
  orders: BacktestOrderResponse[];
  executions: BacktestExecutionResponse[];
}

// --- sandbox (U7) ---
export interface SandboxAccountResponse {
  account_id: string;
}

export interface SandboxPayInRequest {
  account_id: string;
  amount: string;
  currency: string;
}

export interface SandboxPayInResponse {
  account_id: string;
  balance: string;
}

// --- accounts / instruments / market data (U1, U7) ---
export interface AccountInfo {
  account_id: string;
  id: number | null;
  is_saved: boolean;
  broker: string;
  currency: string;
  available_cash: string;
  equity: string;
  currencies: string[];
  name: string | null;
  account_type: string | null;
  status: string | null;
  opened_at: string | null;
  closed_at: string | null;
  positions?: PositionInfo[];
}

export interface PositionInfo {
  account_id: string;
  figi: string;
  ticker: string | null;
  instrument_type: string | null;
  quantity: string;
  average_price: string;
  current_price: string;
  current_value: string;
  unrealized_pnl: string;
  currency: string | null;
  timestamp: string | null;
}

export interface OrderInfo {
  order_id: string;
  account_id: string | null;
  figi: string | null;
  ticker: string | null;
  status: string;
  type: string | null;
  side: string | null;
  requested_quantity: string;
  executed_quantity: string;
  price: string | null;
  currency: string | null;
  created_at: string | null;
  updated_at: string | null;
  reject_info: string | null;
}

export interface DealInfo {
  deal_id: string;
  account_id: string | null;
  order_id: string | null;
  figi: string;
  side: string;
  quantity: string;
  price: string;
  commission: string;
  currency: string | null;
  happened_at: string | null;
}

export interface InstrumentInfo {
  /** Local PostgreSQL id (instruments.id); required by bot/backtest endpoints. */
  id: number | null;
  figi: string;
  ticker: string | null;
  name: string | null;
  instrument_type: string | null;
  currency: string | null;
  lot_size: number | null;
  tick_size: string | null;
  trading_status: string;
  exchange: string | null;
  is_active: boolean;
}

export interface CandleInfo {
  figi: string;
  timeframe: string;
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
  is_complete: boolean;
}

export interface LastPriceInfo {
  figi: string;
  ticker: string | null;
  price: string;
  timestamp: string | null;
}

export interface SyncResponse {
  synced: number;
}
