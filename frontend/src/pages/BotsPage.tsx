import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type {
  AccountInfo,
  BotCreateRequest,
  BotResponse,
  DealResponse,
  InstrumentInfo,
  StrategyResponse,
  StrategyVersionOption,
} from "../types";
import { Button, ErrorBanner, Field, Loading, SelectInput, TextInput } from "../components/FormControls";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useRuntime } from "../lib/useRuntime";
import { BOT_STATUS_LABELS, CLOSE_REASON_LABELS, DEAL_STATUS_LABELS, LEVEL_STATUS_LABELS } from "../lib/labels";
import { getPollIntervalMs } from "../lib/settings";

function StatusBadge(props: { status: string }) {
  const label = BOT_STATUS_LABELS[props.status] ?? props.status;
  const cls =
    props.status === "RUNNING"
      ? "bg-emerald-900/50 text-emerald-200"
      : props.status === "ERROR" || props.status === "EMERGENCY_STOP"
        ? "bg-red-900/60 text-red-200"
        : props.status === "STARTING" || props.status === "STOP_REQUESTED"
          ? "bg-amber-900/50 text-amber-200"
          : "bg-zinc-800 text-zinc-300";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{label}</span>;
}

/** U2: lifecycle actions with a START confirmation in live mode. */
export function BotActions(props: { bot: BotResponse; onChanged: () => void; onError: (message: string) => void }) {
  const { bot, onChanged, onError } = props;
  const { runtime } = useRuntime();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const act = useCallback(
    async (action: "start" | "stop" | "emergency-stop") => {
      setBusy(true);
      try {
        await api.post<BotResponse>(`/api/bots/${bot.id}/${action}`);
        onChanged();
      } catch (err) {
        onError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [bot.id, onChanged, onError],
  );

  const live = runtime?.sandbox === false;

  const doStart = () => {
    setConfirming(false);
    void act("start");
  };

  return (
    <div className="flex flex-wrap gap-2">
      {bot.status === "STOPPED" || bot.status === "ERROR" || bot.status === "EMERGENCY_STOP" ? (
        <Button onClick={() => (live ? setConfirming(true) : void act("start"))} disabled={busy}>
          {live ? "Старт (подтвердите)" : "Старт"}
        </Button>
      ) : null}
      {bot.status === "RUNNING" || bot.status === "STARTING" || bot.status === "STOP_REQUESTED" ? (
        <Button variant="ghost" onClick={() => void act("stop")} disabled={busy}>
          Стоп
        </Button>
      ) : null}
      {bot.status === "RUNNING" || bot.status === "STARTING" ? (
        <Button variant="danger" onClick={() => void act("emergency-stop")} disabled={busy}>
          Экстренная остановка
        </Button>
      ) : null}
      <ConfirmDialog
        open={confirming}
        title="Запустить бота на реальном счёте?"
        message={
          <p>
            Бот «{bot.name}» будет запущен на <b>боевом счёте</b> (реальные деньги).
            <br />
            Счёт: {bot.account_id ?? "—"} · Инструмент: {bot.instrument_id ?? "—"} · Депозит: {bot.deposit ?? "—"}
            <br />
            Убедитесь, что стратегия, счёт и параметры верны.
          </p>
        }
        confirmLabel="Запустить"
        danger
        onConfirm={doStart}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}

export function BotsPage() {
  const [bots, setBots] = useState<BotResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [pollMs, setPollMs] = useState(getPollIntervalMs());
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setError(null);
    try {
      setBots(await api.get<BotResponse[]>("/api/bots"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (pollMs <= 0) return;
    const t = window.setInterval(() => void load(), pollMs);
    return () => window.clearInterval(t);
  }, [pollMs, load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Боты</h2>
        <div className="flex items-center gap-2">
          <label className="text-xs text-zinc-500">
            Автообновление:{" "}
            <select
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs"
              value={String(pollMs)}
              onChange={(e) => {
                const v = Number(e.target.value);
                setPollMs(v);
              }}
            >
              <option value="0">выкл</option>
              <option value="5000">5 секунд</option>
              <option value="10000">10 секунд</option>
              <option value="30000">30 секунд</option>
            </select>
          </label>
          <Button onClick={() => setShowCreate((v) => !v)}>{showCreate ? "Отмена" : "+ Создать бота"}</Button>
        </div>
      </div>
      <ErrorBanner text={error} />
      {showCreate ? <CreateBotPanel onCreated={() => { setShowCreate(false); void load(); }} /> : null}
      {!bots ? (
        <Loading />
      ) : bots.length === 0 ? (
        <p className="text-sm text-zinc-500">Ботов пока нет.</p>
      ) : (
        <div className="space-y-2">
          {bots.map((bot) => (
            <div key={bot.id} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <Link to={`/bots/${bot.id}`} className="font-medium text-zinc-100 hover:underline">
                    {bot.name}
                  </Link>
                  <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-zinc-500">
                    <StatusBadge status={bot.status} />
                    <span>Счёт: {bot.account_id ?? "—"}</span>
                    <span>Инструмент: {bot.instrument_id ?? "—"}</span>
                    <span>Депозит: {bot.deposit ?? "—"}</span>
                    {bot.last_error ? <span className="max-w-md truncate text-red-400" title={bot.last_error}>ошибка: {bot.last_error}</span> : null}
                    {bot.last_skip_reason ? <span title={bot.last_skip_reason}>пропуск: {bot.last_skip_reason}</span> : null}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="ghost" onClick={() => navigate(`/bots/${bot.id}`)}>
                    Сделка
                  </Button>
                  <BotActions bot={bot} onChanged={load} onError={(m) => setError(m)} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CreateBotPanel(props: { onCreated: () => void }) {
  const [strategies, setStrategies] = useState<StrategyResponse[]>([]);
  const [versions, setVersions] = useState<StrategyVersionOption[]>([]);
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [instruments, setInstruments] = useState<InstrumentInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState("");
  const [strategyId, setStrategyId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [instrumentId, setInstrumentId] = useState("");
  const [deposit, setDeposit] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const [st, acc, inst] = await Promise.all([
          api.get<StrategyResponse[]>("/api/strategies"),
          api.get<AccountInfo[]>("/api/accounts"),
          api.get<InstrumentInfo[]>("/api/instruments?active=true"),
        ]);
        setStrategies(st);
        setAccounts(acc.filter((a) => a.id !== null));
        setInstruments(inst.filter((i) => i.id !== null));
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
      setVersions(await api.get<StrategyVersionOption[]>(`/api/strategies/${sid}/versions`));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const submit = async () => {
    setError(null);
    const payload: BotCreateRequest = {
      name: name.trim(),
      strategy_version_id: Number(versionId),
      account_id: Number(accountId),
      instrument_id: Number(instrumentId),
      deposit: deposit.trim() === "" ? null : deposit.trim(),
    };
    setBusy(true);
    try {
      await api.post<BotResponse>("/api/bots", payload);
      props.onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
      <h3 className="mb-3 font-medium text-zinc-200">Новый бот</h3>
      <ErrorBanner text={error} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Field label="Название" required>
          <TextInput value={name} onChange={setName} />
        </Field>
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
        <Field label="Счёт (локальный)" required>
          <SelectInput
            value={accountId}
            onChange={setAccountId}
            allowEmpty
            emptyLabel="— выберите —"
            options={accounts.map((a) => ({ value: String(a.id), label: `#${a.id} · ${a.name ?? a.account_id}` }))}
          />
        </Field>
        <Field label="Инструмент (локальный)" required>
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
        <Field label="Депозит (необязательно)">
          <TextInput value={deposit} onChange={setDeposit} placeholder="например, 100000" />
        </Field>
      </div>
      <div className="mt-4 flex justify-end">
        <Button onClick={() => void submit()} disabled={busy || !name.trim() || !versionId || !accountId || !instrumentId}>
          Создать (в состоянии «Остановлен»)
        </Button>
      </div>
    </div>
  );
}

export function BotDetailPage() {
  const { id } = useParams();
  const botId = id ? Number(id) : null;
  const [bot, setBot] = useState<BotResponse | null>(null);
  const [openDeal, setOpenDeal] = useState<DealResponse | null>(null);
  const [deals, setDeals] = useState<DealResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    if (botId === null) return;
    try {
      const [b, d, history] = await Promise.all([
        api.get<BotResponse>(`/api/bots/${botId}`),
        api.get<DealResponse | null>(`/api/bots/${botId}/deal`),
        api.get<DealResponse[]>(`/api/bots/${botId}/deals?limit=50`),
      ]);
      setBot(b);
      setOpenDeal(d);
      setDeals(history);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [botId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const t = window.setInterval(() => void load(), getPollIntervalMs());
    return () => window.clearInterval(t);
  }, [load]);

  if (error && !bot) {
    return (
      <div className="space-y-3">
        <ErrorBanner text={error} />
        <Button variant="ghost" onClick={() => navigate("/bots")}>Назад</Button>
      </div>
    );
  }
  if (!bot) return <Loading />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{bot.name}</h2>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-zinc-500">
            <StatusBadge status={bot.status} />
            <span>Стратегия: версия {bot.strategy_version_id ?? "—"}</span>
            <span>Счёт: {bot.account_id ?? "—"}</span>
            <span>Инструмент: {bot.instrument_id ?? "—"}</span>
            <span>Депозит: {bot.deposit ?? "—"}</span>
            {bot.started_at ? <span>Запущен: {new Date(bot.started_at).toLocaleString("ru-RU")}</span> : null}
            {bot.stopped_at ? <span>Остановлен: {new Date(bot.stopped_at).toLocaleString("ru-RU")}</span> : null}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => navigate("/bots")}>К списку</Button>
          <BotActions bot={bot} onChanged={load} onError={setError} />
        </div>
      </div>
      <ErrorBanner text={error} />
      {bot.last_error ? (
        <div className="rounded border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {bot.last_error}
        </div>
      ) : null}
      {bot.last_skip_reason ? (
        <p className="text-xs text-amber-300">Последний пропуск цикла: {bot.last_skip_reason}</p>
      ) : null}
      {bot.deal_error ? (
        <p className="text-xs text-red-400">Ошибка сделки: {bot.deal_error}</p>
      ) : null}

      <section>
        <h3 className="mb-2 font-medium text-zinc-200">Текущая сделка</h3>
        {openDeal ? <DealCard deal={openDeal} /> : <p className="text-sm text-zinc-500">Открытых сделок нет.</p>}
      </section>

      <section>
        <h3 className="mb-2 font-medium text-zinc-200">История сделок</h3>
        {deals.length === 0 ? (
          <p className="text-sm text-zinc-500">Закрытых сделок нет.</p>
        ) : (
          <div className="space-y-2">
            {deals.map((d) => <DealCard key={d.id} deal={d} />)}
          </div>
        )}
      </section>
    </div>
  );
}

function DealCard(props: { deal: DealResponse }) {
  const d = props.deal;
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500">
        <span>Сделка #{d.id}</span>
        <span>FIGI: {d.instrument_figi}</span>
        <span>Направление: {d.direction === "LONG" ? "Лонг" : "Шорт"}</span>
        <span className={d.status === "CLOSED" ? "text-zinc-400" : "text-amber-300"}>
          {DEAL_STATUS_LABELS[d.status] ?? d.status}
        </span>
        {d.close_reason ? (
          <span className="text-emerald-300">Причина закрытия: {CLOSE_REASON_LABELS[d.close_reason] ?? d.close_reason}</span>
        ) : null}
        {d.stop_bot_after === true ? <span>бот остановлен после срабатывания</span> : null}
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Info label="Опорная цена" value={d.reference_price} />
        <Info label="Средняя цена" value={d.average_price} />
        <Info label="Позиция" value={d.position_quantity} />
        <Info label="TP %" value={d.tp_percent} />
        <Info label="TP цена" value={d.tp_price} />
        <Info label="SL %" value={d.sl_percent} />
        <Info label="SL цена" value={d.sl_price} />
        <Info label="SL активен" value={d.sl_active === null ? "—" : d.sl_active ? "да" : "нет"} />
      </div>
      {d.levels.length > 0 ? (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500">
                <th className="py-1 pr-3">№</th>
                <th className="pr-3">Сторона</th>
                <th className="pr-3">Цена</th>
                <th className="pr-3">Номинал</th>
                <th className="pr-3">Кол-во</th>
                <th className="pr-3">Смещение %</th>
                <th className="pr-3">Статус</th>
                <th className="pr-3">Исполнено</th>
                <th>Заявка</th>
              </tr>
            </thead>
            <tbody>
              {d.levels.map((lv) => (
                <tr key={lv.index} className="border-b border-zinc-900">
                  <td className="py-1 pr-3">{lv.index}</td>
                  <td className="pr-3">{lv.side === "BUY" ? "Покупка" : "Продажа"}</td>
                  <td className="pr-3">{lv.price ?? "—"}</td>
                  <td className="pr-3">{lv.nominal}</td>
                  <td className="pr-3">{lv.quantity}</td>
                  <td className="pr-3">{lv.offset_percent}</td>
                  <td className="pr-3">{LEVEL_STATUS_LABELS[lv.status] ?? lv.status}</td>
                  <td className="pr-3">{lv.filled_quantity}</td>
                  <td className="pr-3">{lv.broker_order_id ?? lv.order_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function Info(props: { label: string; value: unknown }) {
  return (
    <div>
      <p className="text-xs text-zinc-500">{props.label}</p>
      <p className="font-mono text-xs text-zinc-200">{String(props.value ?? "—")}</p>
    </div>
  );
}
