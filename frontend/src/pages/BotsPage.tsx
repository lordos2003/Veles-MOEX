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
import { Button, ErrorBanner, Field, Loading, SelectInput, TextInput, TableWrap } from "../components/FormControls";
import { InstrumentPicker } from "../components/InstrumentPicker";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";
import {
  AccountErrorNote,
  BotSettingsPanel,
  accountLabel,
  instrumentLabel,
  useBotDisplayMeta,
  versionLabel,
} from "../components/BotSettingsPanel";
import { useRuntime } from "../lib/useRuntime";
import { BOT_STATUS_LABELS, CLOSE_REASON_LABELS, DEAL_STATUS_LABELS, LEVEL_STATUS_LABELS } from "../lib/labels";
import { usePolling, usePollInterval } from "../lib/usePolling";

function StatusBadge(props: { status: string }) {
  const label = BOT_STATUS_LABELS[props.status] ?? props.status;
  const cls =
    props.status === "RUNNING"
      ? "bg-success-soft/70 text-success"
      : props.status === "ERROR" || props.status === "EMERGENCY_STOP"
        ? "bg-error-soft/70 text-error"
        : props.status === "STARTING" || props.status === "STOP_REQUESTED"
          ? "bg-warning-soft/70 text-warning"
          : "bg-surface-raised text-text-secondary";
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>{label}</span>;
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
  const [pollMs, setPollMs] = usePollInterval();
  const navigate = useNavigate();
  const meta = useBotDisplayMeta();

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

  const poll = useCallback(() => void load(), [load]);
  usePolling(poll, pollMs);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Боты"
        description="Запуск, остановка и состояние торговых ботов; список обновляется автоматически."
        actions={
          <>
            <label className="text-xs text-text-muted">
              Автообновление:{" "}
              <select
                className="min-h-9 rounded-control border border-border bg-control px-2 py-1 text-xs text-text"
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
          </>
        }
      />
      <ErrorBanner text={error} />
      {showCreate ? <CreateBotPanel onCreated={() => { setShowCreate(false); void load(); }} /> : null}
      {!bots ? (
        <Loading />
      ) : bots.length === 0 ? (
        <p className="text-sm text-text-muted">Ботов пока нет.</p>
      ) : (
        <div className="space-y-2">
          {bots.map((bot) => (
            <div key={bot.id} className="rounded-card border border-border-soft bg-surface/60 p-4 shadow-card">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <Link to={`/bots/${bot.id}`} className="inline-flex min-h-8 items-center text-base font-medium text-text hover:underline">
                    {bot.name}
                  </Link>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-muted">
                    <StatusBadge status={bot.status} />
                    <span>Счёт: {accountLabel(meta, bot.account_id) ?? "—"}<AccountErrorNote meta={meta} /></span>
                    <span>Инструмент: {instrumentLabel(meta, bot.instrument_id) ?? "—"}</span>
                    <span>Стратегия: {versionLabel(meta, bot.strategy_version_id) ?? "—"}</span>
                    <span>Депозит: {bot.deposit ?? "—"}</span>
                    {bot.last_error ? <span className="max-w-md truncate text-error" title={bot.last_error}>ошибка: {bot.last_error}</span> : null}
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
              <div className="mt-2">
                <BotSettingsPanel
                  bot={bot}
                  meta={meta}
                  onChanged={load}
                  onError={(m) => setError(m)}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CreateBotPanel(props: { onCreated: () => void }) {
  /**
   * G5 (MVP-8.0, замечание M1 ревью MVP-7.7): strategies / accounts /
   * instruments load independently, so a broker failure (`/api/accounts`)
   * hides neither the paper picker nor the strategy list. Each error is shown
   * verbatim next to its own field only.
   */
  const [strategies, setStrategies] = useState<StrategyResponse[] | null>(null);
  const [strategiesError, setStrategiesError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<AccountInfo[] | null>(null);
  const [accountsError, setAccountsError] = useState<string | null>(null);
  const [instruments, setInstruments] = useState<InstrumentInfo[] | null>(null);
  const [instrumentsError, setInstrumentsError] = useState<string | null>(null);
  const [versions, setVersions] = useState<StrategyVersionOption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState("");
  const [strategyId, setStrategyId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [instrumentId, setInstrumentId] = useState("");
  const [deposit, setDeposit] = useState("");

  useEffect(() => {
    let cancelled = false;
    const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

    void (async () => {
      try {
        const st = await api.get<StrategyResponse[]>("/api/strategies");
        if (!cancelled) {
          setStrategies(st);
          setStrategiesError(null);
        }
      } catch (err) {
        if (!cancelled) setStrategiesError(message(err));
      }
    })();
    void (async () => {
      try {
        const acc = await api.get<AccountInfo[]>("/api/accounts");
        if (!cancelled) {
          setAccounts(acc.filter((a) => a.id !== null));
          setAccountsError(null);
        }
      } catch (err) {
        if (!cancelled) setAccountsError(message(err));
      }
    })();
    void (async () => {
      try {
        const inst = await api.get<InstrumentInfo[]>("/api/instruments?active=true");
        if (!cancelled) {
          setInstruments(inst.filter((i) => i.id !== null));
          setInstrumentsError(null);
        }
      } catch (err) {
        if (!cancelled) setInstrumentsError(message(err));
      }
    })();

    return () => {
      cancelled = true;
    };
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

  /**
   * MVP-7.7 P1/P2: the picker works by FIGI; the panel keeps the local
   * `instrument_id`. Papers without a local id are filtered out at load.
   */
  const chosenInstrument = (instruments ?? []).find((i) => String(i.id) === instrumentId);
  const instrumentFigi = chosenInstrument ? chosenInstrument.figi : "";
  const onSelectInstrument = (figi: string) => {
    const inst = (instruments ?? []).find((i) => i.figi === figi);
    setInstrumentId(inst ? String(inst.id) : "");
  };

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
    <div className="rounded-card border border-border-soft bg-surface/60 p-4 shadow-card sm:p-5">
      <h3 className="mb-3 font-medium text-text">Новый бот</h3>
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
              options={(strategies ?? []).map((s) => ({ value: String(s.id), label: s.name }))}
            />
            {strategiesError ? <p className="text-xs text-error">{strategiesError}</p> : null}
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
            options={(accounts ?? []).map((a) => ({ value: String(a.id), label: `#${a.id} · ${a.name ?? a.account_id}` }))}
          />
          {accountsError ? <p className="text-xs text-error">{accountsError}</p> : null}
        </Field>
        <Field label="Ценная бумага" required>
          {instrumentsError ? (
            <p className="text-sm text-error">{instrumentsError}</p>
          ) : !instruments || instruments.length === 0 ? (
            <p className="text-sm text-text-muted">Инструменты не загружены.</p>
          ) : (
            <InstrumentPicker
              instruments={instruments}
              selectedFigi={instrumentFigi}
              onSelect={onSelectInstrument}
              fallbackLabel={instrumentId ? `#${instrumentId}` : ""}
              listId="create-bot-instrument-results"
            />
          )}
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
  const meta = useBotDisplayMeta();
  const [pollMs] = usePollInterval();

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

  const poll = useCallback(() => void load(), [load]);
  usePolling(poll, pollMs);

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
      <PageHeader
        title={bot.name}
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <StatusBadge status={bot.status} />
            <span>Стратегия: {versionLabel(meta, bot.strategy_version_id) ?? "—"}</span>
            <span>Счёт: {accountLabel(meta, bot.account_id) ?? "—"}<AccountErrorNote meta={meta} /></span>
            <span>Инструмент: {instrumentLabel(meta, bot.instrument_id) ?? "—"}</span>
            <span>Депозит: {bot.deposit ?? "—"}</span>
            {bot.started_at ? <span>Запущен: {new Date(bot.started_at).toLocaleString("ru-RU")}</span> : null}
            {bot.stopped_at ? <span>Остановлен: {new Date(bot.stopped_at).toLocaleString("ru-RU")}</span> : null}
          </span>
        }
        actions={
          <>
            <Button variant="ghost" onClick={() => navigate("/bots")}>К списку</Button>
            <BotActions bot={bot} onChanged={load} onError={setError} />
          </>
        }
      />
      <ErrorBanner text={error} />
      {bot.last_error ? (
        <div className="rounded-control border border-error-border bg-error-soft/70 px-3 py-2 text-sm text-error">
          {bot.last_error}
        </div>
      ) : null}
      {bot.last_skip_reason ? (
        <p className="text-xs text-warning">Последний пропуск цикла: {bot.last_skip_reason}</p>
      ) : null}
      {bot.deal_error ? (
        <p className="text-xs text-error">Ошибка сделки: {bot.deal_error}</p>
      ) : null}

      <BotSettingsPanel
        bot={bot}
        meta={meta}
        onChanged={load}
        onError={setError}
        openDeal={openDeal}
        onDeleted={() => navigate("/bots")}
      />

      <section>
        <h3 className="mb-2 text-base font-medium text-text">Текущая сделка</h3>
        {openDeal ? <DealCard deal={openDeal} /> : <p className="text-sm text-text-muted">Открытых сделок нет.</p>}
      </section>

      <section>
        <h3 className="mb-2 text-base font-medium text-text">История сделок</h3>
        {deals.length === 0 ? (
          <p className="text-sm text-text-muted">Закрытых сделок нет.</p>
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
    <div className="rounded-card border border-border-soft bg-surface/60 shadow-card p-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted">
        <span>Сделка #{d.id}</span>
        <span>FIGI: {d.instrument_figi}</span>
        <span>Направление: {d.direction === "LONG" ? "Лонг" : "Шорт"}</span>
        <span className={d.status === "CLOSED" ? "text-text-muted" : "text-warning"}>
          {DEAL_STATUS_LABELS[d.status] ?? d.status}
        </span>
        {d.close_reason ? (
          <span className="text-success">Причина закрытия: {CLOSE_REASON_LABELS[d.close_reason] ?? d.close_reason}</span>
        ) : null}
        {d.stop_bot_after === true ? <span>бот остановлен после срабатывания</span> : null}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
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
        <div className="mt-3">
          <TableWrap label="Таблица уровней сетки">
          <table className="data-table num">
            <thead>
              <tr>
                <th>№</th>
                <th>Сторона</th>
                <th>Цена</th>
                <th>Номинал</th>
                <th>Кол-во</th>
                <th>Смещение %</th>
                <th>Статус</th>
                <th>Исполнено</th>
                <th>Заявка</th>
              </tr>
            </thead>
            <tbody>
              {d.levels.map((lv) => (
                <tr key={lv.index}>
                  <td>{lv.index}</td>
                  <td>{lv.side === "BUY" ? "Покупка" : "Продажа"}</td>
                  <td>{lv.price ?? "—"}</td>
                  <td>{lv.nominal}</td>
                  <td>{lv.quantity}</td>
                  <td>{lv.offset_percent}</td>
                  <td>{LEVEL_STATUS_LABELS[lv.status] ?? lv.status}</td>
                  <td>{lv.filled_quantity}</td>
                  <td>{lv.broker_order_id ?? lv.order_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </TableWrap>
        </div>
      ) : null}
    </div>
  );
}

function Info(props: { label: string; value: unknown }) {
  return (
    <div>
      <p className="text-xs text-text-muted">{props.label}</p>
      <p className="num text-xs text-text">{String(props.value ?? "—")}</p>
    </div>
  );
}
