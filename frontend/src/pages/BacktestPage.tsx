import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  BacktestRequest,
  BacktestResponse,
  CandleInfo,
  InstrumentInfo,
  StrategyResponse,
  StrategyVersionResponse,
} from "../types";
import { Button, ErrorBanner, Field, Loading, SelectInput, TextareaInput, TextInput } from "../components/FormControls";
import { InstrumentPicker } from "../components/InstrumentPicker";
import CandleChart, { ChartMarker } from "../components/CandleChart";
import { PeriodPicker, PeriodRange } from "../components/PeriodPicker";

const TF_CHOICES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"];

/**
 * MVP-7.7 P3: значения по умолчанию для «Бэктеста» — константа интерфейса,
 * не значение схемы и не Veles-семантика. Решение владельца 2026-10-09,
 * тариф «Инвестор» Т-Инвестиций, акции.
 */
const MAKER_FEE_DEFAULT = "0.003";
const TAKER_FEE_DEFAULT = "0.003";
const SLIPPAGE_DEFAULT = "0.001";

/** MVP-7.6 H4: intraday timeframes use the first 1-minute candle date. */
const MINUTE_TFS = new Set(["1m", "5m", "15m", "30m", "1h", "4h"]);
/** Daily and coarser timeframes use the first 1-day candle date. */
const DAY_TFS = new Set(["1d", "1w", "1mo"]);

/**
 * MVP-7.6 U12: convert a UTC ISO instant from the API to the local calendar
 * date key "YYYY-MM-DD" the picker expects. The boundary follows the browser
 * timezone (the same one used when the period is submitted).
 */
function toLocalDateKey(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

export function BacktestPage() {
  const [strategies, setStrategies] = useState<StrategyResponse[]>([]);
  const [versions, setVersions] = useState<StrategyVersionResponse[]>([]);
  const [instruments, setInstruments] = useState<InstrumentInfo[]>([]);

  const [useVersion, setUseVersion] = useState(true);
  const [strategyId, setStrategyId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [inlineConfig, setInlineConfig] = useState("");
  const [inlineError, setInlineError] = useState<string | null>(null);

  const [instrumentId, setInstrumentId] = useState("");
  const [period, setPeriod] = useState<PeriodRange>({ from: null, to: null });
  const [deposit, setDeposit] = useState("");
  const [makerFee, setMakerFee] = useState(MAKER_FEE_DEFAULT);
  const [takerFee, setTakerFee] = useState(TAKER_FEE_DEFAULT);
  const [slippage, setSlippage] = useState(SLIPPAGE_DEFAULT);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [chart, setChart] = useState<{ candles: CandleInfo[]; markers: ChartMarker[] } | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [st, inst] = await Promise.all([
          api.get<StrategyResponse[]>("/api/strategies"),
          api.get<InstrumentInfo[]>("/api/instruments?active=true"),
        ]);
        setStrategies(st);
        setInstruments(inst);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  const loadVersions = useCallback(async (sid: string) => {
    setVersions([]);
    setVersionId("");
    if (!sid) return;
    try {
      setVersions(await api.get<StrategyVersionResponse[]>(`/api/strategies/${sid}/versions`));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  /** B3: the run timeframe is taken from the config and is not editable. */
  const configTimeframe = useMemo(() => {
    if (useVersion) {
      const v = versions.find((x) => String(x.id) === versionId);
      const tf = (v?.config as { timeframe?: unknown } | undefined)?.timeframe;
      return typeof tf === "string" ? tf : null;
    }
    try {
      const cfg = JSON.parse(inlineConfig) as { timeframe?: unknown };
      return typeof cfg.timeframe === "string" ? cfg.timeframe : null;
    } catch {
      return null;
    }
  }, [useVersion, versions, versionId, inlineConfig]);

  const [timeframe, setTimeframe] = useState("");

  useEffect(() => {
    if (configTimeframe) setTimeframe(configTimeframe);
  }, [configTimeframe]);

  /**
   * MVP-7.7 P1/P2: the picker works by FIGI; the page keeps the local
   * `instrument_id`. A paper without a local id cannot be selected.
   */
  const chosenInstrument = instruments.find((i) => String(i.id) === instrumentId);
  const instrumentFigi = chosenInstrument?.figi ?? "";
  const onSelectInstrument = (figi: string) => {
    const inst = instruments.find((i) => i.figi === figi);
    setInstrumentId(inst?.id != null ? String(inst.id) : "");
  };

  /**
   * MVP-7.6 U12: earliest history date for the selected instrument and
   * timeframe (H4). No instrument / no timeframe / NULL date -> "no source"
   * (behaviour of MVP-7.5: «Весь период» off, presets unfiltered).
   */
  const earliestAvailable = useMemo(() => {
    const inst = instruments.find((i) => String(i.id) === instrumentId);
    if (!inst || !timeframe) return null;
    const iso = MINUTE_TFS.has(timeframe)
      ? inst.first_1min_candle_date
      : DAY_TFS.has(timeframe)
        ? inst.first_1day_candle_date
        : null;
    return toLocalDateKey(iso);
  }, [instruments, instrumentId, timeframe]);

  const earliestHint = earliestAvailable
    ? (() => {
        const [y, m, d] = earliestAvailable.split("-").map(Number);
        return `Данные для бэктеста доступны с: ${pad2(d)}.${pad2(m)}.${y}`;
      })()
    : "нет данных о доступном диапазоне";

  const run = async () => {
    setError(null);
    setResult(null);
    setChart(null);
    setFieldErrors({});

    if (useVersion && !versionId) {
      setError("Выберите версию стратегии.");
      return;
    }
    if (!useVersion) {
      try {
        JSON.parse(inlineConfig);
        setInlineError(null);
      } catch (e) {
        setInlineError(e instanceof Error ? e.message : String(e));
        setError("Инлайн-конфигурация содержит невалидный JSON.");
        return;
      }
    }
    // B3: empty required fields (except fees, prefilled per owner's decision
    // of 2026-10-09) are reported at the field and the request is not sent.
    const errors: Record<string, string> = {};
    if (!instrumentId) errors.instrument = "Выберите ценную бумагу.";
    if (!configTimeframe && !timeframe.trim()) errors.timeframe = "Выберите таймфрейм.";
    if (!period.from || !period.to) errors.from = "Укажите период.";
    if (!deposit.trim()) errors.deposit = "Укажите депозит сделки.";
    if (!makerFee.trim()) errors.makerFee = "Укажите комиссию.";
    if (!takerFee.trim()) errors.takerFee = "Укажите комиссию.";
    if (!slippage.trim()) errors.slippage = "Укажите проскальзывание.";
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }

    const payload: BacktestRequest = {
      instrument_id: Number(instrumentId),
      timeframe,
      from: period.from!.toISOString(),
      to: period.to!.toISOString(),
      deposit: deposit.trim(),
      maker_fee: makerFee.trim(),
      taker_fee: takerFee.trim(),
      slippage: slippage.trim(),
    };
    if (useVersion) {
      payload.strategy_version_id = Number(versionId);
      payload.config = null;
    } else {
      payload.strategy_version_id = null;
      payload.config = JSON.parse(inlineConfig) as Record<string, unknown>;
    }

    setRunning(true);
    try {
      const res = await api.post<BacktestResponse>("/api/backtests", payload);
      setResult(res);
      const inst = instruments.find((i) => String(i.id) === instrumentId);
      if (inst) {
        await loadChart(res, inst.figi, timeframe, period.from!, period.to!, setChart, setError);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Бэктест</h2>
      <ErrorBanner text={error} />

      <div className="grid grid-cols-1 gap-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm">
            <label className="flex items-center gap-1">
              <input type="radio" checked={useVersion} onChange={() => setUseVersion(true)} />
              По версии стратегии
            </label>
            <label className="flex items-center gap-1">
              <input type="radio" checked={!useVersion} onChange={() => setUseVersion(false)} />
              Инлайн-конфигурация
            </label>
          </div>

          {useVersion ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Стратегия" required>
                <SelectInput
                  value={strategyId}
                  onChange={(v) => {
                    setStrategyId(v);
                    void loadVersions(v);
                  }}
                  allowEmpty
                  emptyLabel="— выберите —"
                  options={strategies.map((s) => ({ value: String(s.id), label: s.name }))}
                />
              </Field>
              <Field label="Версия" required>
                <SelectInput
                  value={versionId}
                  onChange={setVersionId}
                  allowEmpty
                  emptyLabel={strategyId ? "— выберите —" : "сначала стратегия"}
                  options={versions.map((v) => ({ value: String(v.id), label: `версия ${v.version}` }))}
                />
              </Field>
            </div>
          ) : (
            <Field label="Конфигурация (JSON)" required error={inlineError ?? undefined}>
              <TextareaInput
                className="h-40"
                value={inlineConfig}
                onChange={(v) => {
                  setInlineConfig(v);
                  setInlineError(null);
                }}
                placeholder='{"name": "", "direction": "LONG", "entry": {...}, "exit": {...}}'
              />
            </Field>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Ценная бумага" required error={fieldErrors.instrument}>
              {instruments.length === 0 ? (
                <p className="text-sm text-text-muted">Инструменты не загружены.</p>
              ) : (
                <InstrumentPicker
                  instruments={instruments}
                  selectedFigi={instrumentFigi}
                  onSelect={onSelectInstrument}
                  fallbackLabel={instrumentId ? `#${instrumentId}` : ""}
                  listId="backtest-instrument-results"
                />
              )}
            </Field>
            <Field label="Таймфрейм (из конфигурации)" error={fieldErrors.timeframe}>
              {configTimeframe ? (
                <p className="rounded border border-zinc-800 bg-zinc-900 px-3 py-2 font-mono text-sm text-zinc-200">
                  {configTimeframe}
                </p>
              ) : (
                <SelectInput
                  value={timeframe}
                  onChange={setTimeframe}
                  allowEmpty
                  emptyLabel="— выберите —"
                  options={TF_CHOICES.map((t) => ({ value: t, label: t }))}
                />
              )}
            </Field>
            <Field
              label="Период"
              required
              error={fieldErrors.from}
              hint={earliestHint}
            >
              <PeriodPicker
                from={period.from}
                to={period.to}
                onChange={(from, to) => setPeriod({ from, to })}
                earliestAvailable={earliestAvailable}
              />
            </Field>
            <Field label="Депозит сделки" required error={fieldErrors.deposit}>
              <TextInput value={deposit} onChange={setDeposit} placeholder="например, 100000" />
            </Field>
          </div>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Maker-комиссия" required error={fieldErrors.makerFee}>
              <TextInput value={makerFee} onChange={setMakerFee} />
            </Field>
            <Field label="Taker-комиссия" required error={fieldErrors.takerFee}>
              <TextInput value={takerFee} onChange={setTakerFee} />
            </Field>
            <Field label="Проскальзывание" required error={fieldErrors.slippage}>
              <TextInput value={slippage} onChange={setSlippage} />
            </Field>
          </div>
          <p className="text-xs text-text-muted">
            Комиссии задаются долей (например, 0.003 = 0.3%). Для тарифа «Инвестор» в Т-Инвестициях, акции.
          </p>
          <div className="flex justify-end">
            <Button onClick={() => void run()} disabled={running}>
              {running ? "Запуск…" : "Запустить бэктест"}
            </Button>
          </div>
        </div>
      </div>

      {running ? <Loading /> : null}

      {result ? (
        <div className="space-y-4">
          <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
            <h3 className="mb-3 font-medium text-zinc-200">Результат</h3>
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4 lg:grid-cols-6">
              <Metric label="Начальный капитал" value={result.initial_capital} />
              <Metric label="Итоговый капитал" value={result.final_capital} />
              <Metric label="Чистая PnL" value={result.net_pnl} />
              <Metric label="ROI" value={result.roi} />
              <Metric label="Сделок" value={String(result.num_trades)} />
              <Metric label="Прибыльных" value={String(result.winning_trades)} />
              <Metric label="Убыточных" value={String(result.losing_trades)} />
              <Metric label="Win rate" value={result.win_rate} />
              <Metric label="Средняя сделка" value={result.average_trade} />
              <Metric label="Средняя длительность" value={result.average_duration} />
              <Metric label="Макс. просадка" value={result.max_drawdown} />
              <Metric label="Комиссии" value={result.total_fees} />
            </div>
          </section>

          {chart ? (
            <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
              <h3 className="mb-2 font-medium text-zinc-200">График свечей и сделки</h3>
              <CandleChart candles={chart.candles} markers={chart.markers} />
              <div className="mt-1 flex gap-4 text-xs text-text-muted">
                <span><span className="text-yellow-400">●</span> вход</span>
                <span><span className="text-sky-400">●</span> выход</span>
              </div>
            </section>
          ) : null}

          <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
            <h3 className="mb-2 font-medium text-zinc-200">Сделки ({result.deals.length})</h3>
            {result.deals.length === 0 ? (
              <p className="text-sm text-text-muted">Сделок за период нет.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-zinc-800 text-text-muted">
                      <th className="py-1 pr-3">Вход</th>
                      <th className="pr-3">Выход</th>
                      <th className="pr-3">Направление</th>
                      <th className="pr-3">Цена входа</th>
                      <th className="pr-3">Цена выхода</th>
                      <th className="pr-3">Кол-во</th>
                      <th className="pr-3">Чистая PnL</th>
                      <th className="pr-3">Причина</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.deals.map((d) => (
                      <tr key={d.deal_id} className="border-b border-zinc-900">
                        <td className="py-1 pr-3">{new Date(d.entry_time).toLocaleString("ru-RU")}</td>
                        <td className="pr-3">{new Date(d.exit_time).toLocaleString("ru-RU")}</td>
                        <td className="pr-3">{d.direction === "LONG" ? "Лонг" : "Шорт"}</td>
                        <td className="pr-3 font-mono">{d.entry_price}</td>
                        <td className="pr-3 font-mono">{d.exit_price}</td>
                        <td className="pr-3 font-mono">{d.quantity}</td>
                        <td className="pr-3 font-mono">{d.net_pnl}</td>
                        <td className="pr-3">{d.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}

function Metric(props: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-text-muted">{props.label}</p>
      <p className="font-mono text-sm text-zinc-100">{props.value}</p>
    </div>
  );
}

/** Fetch candles for the run period and snap deal timestamps to candle bars. */
async function loadChart(
  result: BacktestResponse,
  figi: string,
  timeframe: string,
  from: Date,
  to: Date,
  setChart: (v: { candles: CandleInfo[]; markers: ChartMarker[] }) => void,
  setError: (m: string) => void,
): Promise<void> {
  if (result.deals.length === 0) return;
  try {
    const candles = await api.get<CandleInfo[]>(
      `/api/market-data/${figi}/candles?timeframe=${encodeURIComponent(timeframe)}&from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(to.toISOString())}`,
    );
    const times = candles.map((c) => c.timestamp);
    const snap = (ts: string) => {
      if (times.includes(ts)) return ts;
      const t = new Date(ts).getTime();
      let best = times[0];
      let bestDiff = Infinity;
      for (const cand of times) {
        const diff = Math.abs(new Date(cand).getTime() - t);
        if (diff < bestDiff) {
          bestDiff = diff;
          best = cand;
        }
      }
      return bestDiff <= 3_600_000 ? best : null; // up to 1h tolerance
    };
    const markers: ChartMarker[] = [];
    for (const d of result.deals) {
      const e = snap(d.entry_time);
      if (e) markers.push({ timestamp: e, price: d.entry_price, kind: "entry" });
      const x = snap(d.exit_time);
      if (x) markers.push({ timestamp: x, price: d.exit_price, kind: "exit" });
    }
    setChart({ candles, markers });
  } catch (err) {
    setError(err instanceof Error ? err.message : String(err));
  }
}
