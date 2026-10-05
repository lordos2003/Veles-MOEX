/**
 * Russian UI labels for the strategy form (task U1/U4).
 *
 * Terms come from the Veles Help Center reference (`Veles Help Center —
 * engineering reference.md`) and the project architecture docs; "перевод
 * проекта" marks terms that have no documented Veles counterpart. The full
 * table (field -> label -> source) is exported as TERMS for the REPORT.
 */

export interface TermRow {
  field: string;
  label: string;
  source: string;
}

const VELES = (term: string) => `Veles: ${term}`;
const PROJECT = "Перевод проекта";

export const TERMS: TermRow[] = [
  { field: "name", label: "Название", source: PROJECT },
  { field: "direction", label: "Направление", source: VELES("Direction: Long or Short") },
  { field: "timeframe", label: "Таймфрейм", source: VELES("timeframe/interface") },
  { field: "lookback_bars", label: "История, баров", source: PROJECT },
  { field: "entry", label: "Условия входа", source: VELES("Entry conditions") },
  { field: "entry.method", label: "Метод расчёта", source: VELES("At bar close / Once per minute") },
  { field: "entry.groups", label: "Группы фильтров", source: VELES("Multiple filters; groups AND/OR") },
  { field: "arg1 / arg2", label: "Аргумент", source: VELES("Argument 1 + Operator + Argument 2") },
  { field: "operator", label: "Оператор", source: VELES("> < crossing operators") },
  { field: "argument: constant", label: "Константа", source: VELES("constants") },
  { field: "argument: indicator", label: "Индикатор", source: VELES("Flexible indicators") },
  { field: "argument: candle", label: "Свеча", source: VELES("Candle: Open/Close/High/Low/Volume + shift") },
  { field: "indicator.shift", label: "Сдвиг (баров)", source: VELES("shift") },
  { field: "dca_grid", label: "Ордера (сетка)", source: VELES("DCA/grid") },
  { field: "dca_grid.mode", label: "Режим", source: VELES("Trading mode: Simple / Custom / Signal") },
  { field: "dca_grid.levels", label: "Уровней", source: VELES("Grid order count") },
  { field: "dca_grid.overlap_percent", label: "Перекрытие (%)", source: VELES("Price-change overlap") },
  { field: "dca_grid.spacing_percent", label: "Шаг (%)", source: VELES("overlap/spacing") },
  { field: "dca_grid.martingale_percent", label: "Мартингейл (%)", source: VELES("Martingale percentage") },
  { field: "dca_grid.logarithmic_factor", label: "Логарифм. коэффициент", source: VELES("Logarithmic price distribution") },
  { field: "dca_grid.first_order_offset_percent", label: "Смещение 1-го ордера (%)", source: VELES("First-order offset") },
  { field: "dca_grid.pull_up_percent", label: "Подтяжка сетки (%)", source: VELES("Grid pull-up / refresh") },
  { field: "dca_grid.active_limit", label: "Лимит активных заявок", source: VELES("orders visible in advance") },
  { field: "dca_grid.custom_levels", label: "Уровни сетки", source: VELES("custom grid") },
  { field: "dca_grid.signal_groups", label: "Сигнальные группы", source: VELES("Signal mode") },
  { field: "exit", label: "Тейк-профит и выход", source: VELES("Take-profit mode") },
  { field: "exit.take_profit", label: "Тейк-профит", source: VELES("Take-profit mode: Simple / Custom / Signal") },
  { field: "take_profit: fixed_percentage", label: "Фиксированный процент", source: VELES("fixed profit") },
  { field: "take_profit: multi_take", label: "Несколько частичных", source: VELES("multiple partial exits") },
  { field: "take_profit: signal", label: "Сигнальный", source: VELES("indicators/signals exits") },
  { field: "take_profit: trailing", label: "Трейлинг", source: PROJECT },
  { field: "exit.stop_loss", label: "Стоп-лосс", source: VELES("Stop-loss") },
  { field: "exit.stop_loss.percent", label: "Процент стопа", source: VELES("E1: сверх перекрытия сетки от цены первого ордера") },
  { field: "exit.stop_loss.stop_bot_after", label: "Остановить бота после стопа", source: VELES("Stop bot after N deals") },
  { field: "exit.signal_stop", label: "Сигнальный стоп-лосс", source: VELES("Stop-loss (signal)") },
  { field: "risk", label: "Риск", source: VELES("Risk management principles") },
  { field: "risk.max_position_size", label: "Макс. размер позиции", source: PROJECT },
  { field: "risk.max_concurrent_bots", label: "Макс. одновременных ботов", source: PROJECT },
  { field: "risk.daily_loss_limit", label: "Дневной лимит убытка", source: PROJECT },
  { field: "risk.emergency_stop", label: "Экстренная остановка", source: VELES("emergency stop / safety controls") },
];

const PATH_LABELS: Record<string, string> = {};
for (const row of TERMS) PATH_LABELS[row.field] = row.label;
// Argument sub-fields (not part of the REPORT table; small helper entries).
PATH_LABELS["constant.value"] = "Значение";
PATH_LABELS["indicator.name"] = "Индикатор";
PATH_LABELS["indicator.timeframe"] = "Таймфрейм";
PATH_LABELS["indicator.period"] = "Период";
PATH_LABELS["indicator.method"] = "Метод";
PATH_LABELS["indicator.series"] = "Серия";
PATH_LABELS["indicator.shift"] = "Сдвиг (баров)";
PATH_LABELS["candle.timeframe"] = "Таймфрейм";
PATH_LABELS["candle.series"] = "Серия свечи";
PATH_LABELS["candle.shift"] = "Сдвиг (баров)";

const SEGMENT_LABELS: Record<string, string> = {
  name: "Название",
  description: "Описание",
  direction: "Направление",
  timeframe: "Таймфрейм",
  lookback_bars: "История (баров)",
  instrument_id: "Инструмент (id)",
  method: "Метод",
  groups: "Группы фильтров",
  conditions: "Условия",
  arg1: "Аргумент 1",
  arg2: "Аргумент 2",
  operator: "Оператор",
  kind: "Тип",
  value: "Значение",
  period: "Период",
  shift: "Сдвиг (баров)",
  series: "Серия",
  name_ind: "Индикатор",
  params: "Параметры",
  mode: "Режим",
  levels: "Уровней",
  overlap_percent: "Перекрытие (%)",
  spacing_percent: "Шаг (%)",
  martingale_percent: "Мартингейл (%)",
  logarithmic_factor: "Логарифм. коэффициент",
  first_order_offset_percent: "Смещение 1-го ордера (%)",
  pull_up_percent: "Подтяжка сетки (%)",
  active_limit: "Лимит активных заявок",
  custom_levels: "Уровни сетки",
  signal_groups: "Сигнальные группы",
  signal_offset_type: "Тип смещения сигнала",
  signal_min_offset_percent: "Мин. смещение (%)",
  offset_percent: "Смещение (%)",
  nominal_percent: "Номинал (%)",
  volume_percent: "Объём (%)",
  takes: "Частичные тейки",
  breakeven: "Безубыток",
  reference: "Опорная цена",
  deviation_percent: "Отклонение (%)",
  min_pnl_percent: "Мин. PnL (%)",
  percent: "Процент",
  stop_bot_after: "Остановить бота после стопа",
  offset_enabled: "Смещение включено",
  min_offset_percent: "Мин. смещение (%)",
  max_position_size: "Макс. размер позиции",
  max_concurrent_bots: "Макс. одновременных ботов",
  daily_loss_limit: "Дневной лимит убытка",
  emergency_stop: "Экстренная остановка",
};

/** Russian label for a config path like "exit.stop_loss.percent". */
export function labelFor(path: string): string {
  if (PATH_LABELS[path]) return PATH_LABELS[path];
  const parts = path.split(".");
  for (let i = parts.length; i > 0; i -= 1) {
    const candidate = parts.slice(0, i).join(".");
    if (PATH_LABELS[candidate]) return PATH_LABELS[candidate];
  }
  const last = parts[parts.length - 1];
  if (last === "name") return "Название";
  if (last === "period") return "Период";
  if (last === "method") return "Метод";
  if (last === "timeframe") return "Таймфрейм";
  if (last === "series") return "Серия";
  if (last === "shift") return "Сдвиг (баров)";
  if (last === "value") return "Значение";
  if (last === "percent") return "Процент";
  return SEGMENT_LABELS[last] ?? last;
}

/** Hint (tooltip) text for a config path. */
export function hintFor(path: string): string | null {
  if (path === "exit.stop_loss.percent") {
    return "Процент сверх перекрытия сетки от цены первого ордера (E1).";
  }
  if (path === "exit.stop_loss.stop_bot_after") {
    return "Остановить бота после закрытия сделки по стоп-лоссу (E3).";
  }
  if (path.endsWith(".groups")) {
    return "Между группами — ИЛИ, внутри группы — И.";
  }
  return null;
}

export interface OptionDef {
  value: string;
  label: string;
}

export function optionLabel(options: OptionDef[], value: unknown): string {
  const found = options.find((o) => o.value === value);
  return found ? found.label : value === null || value === undefined ? "—" : String(value);
}

export const DIRECTION_OPTIONS: OptionDef[] = [
  { value: "LONG", label: "Лонг" },
  { value: "SHORT", label: "Шорт" },
];

export const TIMEFRAME_OPTIONS: OptionDef[] = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"].map(
  (t) => ({ value: t, label: t }),
);

export const METHOD_OPTIONS: OptionDef[] = [
  { value: "at_bar_close", label: "По закрытию бара" },
  { value: "per_minute", label: "Раз в минуту" },
];

export const OPERATOR_OPTIONS: OptionDef[] = [
  { value: ">", label: "больше" },
  { value: "<", label: "меньше" },
  { value: "cross_up", label: "пересечение вверх" },
  { value: "cross_down", label: "пересечение вниз" },
];

export const GRID_MODE_OPTIONS: OptionDef[] = [
  { value: "simple", label: "Простой" },
  { value: "custom", label: "Свой" },
  { value: "signal", label: "Сигнал" },
];

export const SERIES_OPTIONS: OptionDef[] = ["open", "high", "low", "close", "volume"].map((s) => ({
  value: s,
  label: s,
}));

export const TP_KIND_OPTIONS: OptionDef[] = [
  { value: "fixed_percentage", label: "Фиксированный процент" },
  { value: "multi_take", label: "Несколько частичных" },
  { value: "signal", label: "Сигнальный" },
  { value: "trailing", label: "Трейлинг" },
];

export const REFERENCE_OPTIONS: OptionDef[] = [
  { value: "average_price", label: "Средняя цена" },
  { value: "previous_take", label: "Предыдущий тейк" },
];

export const STOP_REFERENCE_OPTIONS: OptionDef[] = [
  { value: "average_price", label: "Средняя цена" },
  { value: "last_order", label: "Последний ордер" },
];

export const SIGNAL_OFFSET_OPTIONS: OptionDef[] = [
  { value: "previous_order", label: "От предыдущего ордера" },
  { value: "reference", label: "От опорной цены" },
];

export const ARG_KIND_OPTIONS: OptionDef[] = [
  { value: "constant", label: "Константа" },
  { value: "indicator", label: "Индикатор" },
  { value: "candle", label: "Свеча" },
];

export const BOT_STATUS_LABELS: Record<string, string> = {
  STOPPED: "Остановлен",
  STARTING: "Запускается",
  RUNNING: "Работает",
  STOP_REQUESTED: "Останавливается",
  EMERGENCY_STOP: "Экстренная остановка",
  ERROR: "Ошибка",
};

export const DEAL_STATUS_LABELS: Record<string, string> = {
  OPEN: "Открыта",
  CLOSED: "Закрыта",
  CLOSING: "Закрывается",
  ERROR: "Ошибка",
};

export const CLOSE_REASON_LABELS: Record<string, string> = {
  take_profit: "Тейк-профит",
  stop_loss: "Стоп-лосс",
  manual: "Вручную",
  emergency_stop: "Экстренная остановка",
};

export const LEVEL_STATUS_LABELS: Record<string, string> = {
  PENDING: "Ожидает",
  FILLED: "Исполнен",
  CANCELLED: "Отменён",
  FAILED: "Ошибка",
};

export const ORDER_STATUS_LABELS: Record<string, string> = {
  NEW: "Новая",
  SUBMITTED: "Отправлена",
  PARTIALLY_FILLED: "Частично исполнена",
  FILLED: "Исполнена",
  CANCELLED: "Отменена",
  REJECTED: "Отклонена",
  EXPIRED: "Истекла",
  ERROR: "Ошибка",
  UNKNOWN: "Неизвестно",
};
