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
import { Button, ErrorBanner, Field, Loading, SelectInput, TextInput } from "../components/FormControls";
import CandleChart, { ChartMarker } from "../components/CandleChart";

const TF_CHOICES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"];

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
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [deposit, setDeposit] = useState("");
  const [makerFee, setMakerFee] = useState("");
  const [takerFee, setTakerFee] = useState("");
  const [slippage, setSlippage] = useState("");
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
    // B3: nothing is filled in for the user — empty required fields are
    // reported at the field and the request is not sent.
    const errors: Record<string, string> = {};
    if (!instrumentId) errors.instrument = "Выберите инструмент.";
    if (!configTimeframe && !timeframe.trim()) errors.timeframe = "Выберите таймфрейм.";
    if (!from.trim()) errors.from = "Укажите начало периода.";
    if (!to.trim()) errors.to = "Укажите конец периода.";
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
      from: new Date(from).toISOString(),
      to: new Date(to).toISOString(),
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
        await loadChart(res, inst.figi, timeframe, from, to, setChart, setError);
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
              <textarea
                className="h-40 w-full rounded border border-zinc-700 bg-zinc-950 p-2 font-mono text-xs text-zinc-200"
                value={inlineConfig}
                onChange={(e) => {
                  setInlineConfig(e.target.value);
                  setInlineError(null);
                }}
                spellCheck={false}
                placeholder='{"name": "", "direction": "LONG", "entry": {...}, "exit": {...}}'
              />
            </Field>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Инструмент" required error={fieldErrors.instrument}>
              <SelectInput
                value={instrumentId}
                onChange={setInstrumentId}
                allowEmpty
                emptyLabel="— выберите —"
                options={instruments.map((i) => ({
                  value: String(i.id),
                  label: `${i.ticker ?? i.figi} · ${i.name ?? ""}`,
                }))}
              />
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
            <Field label="С" required error={fieldErrors.from}>
              <TextInput value={from} onChange={setFrom} placeholder="например, 2026-01-01T10:00" />
            </Field>
            <Field label="По" required error={fieldErrors.to}>
              <TextInput value={to} onChange={setTo} placeholder="например, 2026-02-01T10:00" />
            </Field>
            <Field label="Депозит сделки" required error={fieldErrors.deposit}>
              <TextInput value={deposit} onChange={setDeposit} placeholder="например, 100000" />
            </Field>
          </div>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Maker-комиссия" required error={fieldErrors.makerFee}>
              <TextInput value={makerFee} onChange={setMakerFee} placeholder="например, 0.0003" />
            </Field>
            <Field label="Taker-комиссия" required error={fieldErrors.takerFee}>
              <TextInput value={takerFee} onChange={setTakerFee} placeholder="например, 0.0003" />
            </Field>
            <Field label="Проскальзывание" required error={fieldErrors.slippage}>
              <TextInput value={slippage} onChange={setSlippage} placeholder="например, 0.001" />
            </Field>
          </div>
          <p className="text-xs text-zinc-500">
            Комиссии задаются долей (например, 0.0003 = 0.03%). Значения не подставляются автоматически — их
            необходимо указать явно.
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
              <div className="mt-1 flex gap-4 text-xs text-zinc-500">
                <span><span className="text-yellow-400">●</span> вход</span>
                <span><span className="text-sky-400">●</span> выход</span>
              </div>
            </section>
          ) : null}

          <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
            <h3 className="mb-2 font-medium text-zinc-200">Сделки ({result.deals.length})</h3>
            {result.deals.length === 0 ? (
              <p className="text-sm text-zinc-500">Сделок за период нет.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-500">
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
      <p className="text-xs text-zinc-500">{props.label}</p>
      <p className="font-mono text-sm text-zinc-100">{props.value}</p>
    </div>
  );
}

/** Fetch candles for the run period and snap deal timestamps to candle bars. */
async function loadChart(
  result: BacktestResponse,
  figi: string,
  timeframe: string,
  from: string,
  to: string,
  setChart: (v: { candles: CandleInfo[]; markers: ChartMarker[] }) => void,
  setError: (m: string) => void,
): Promise<void> {
  if (result.deals.length === 0) return;
  try {
    const candles = await api.get<CandleInfo[]>(
      `/api/market-data/${figi}/candles?timeframe=${encodeURIComponent(timeframe)}&from=${encodeURIComponent(new Date(from).toISOString())}&to=${encodeURIComponent(new Date(to).toISOString())}`,
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
