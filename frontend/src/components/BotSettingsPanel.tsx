/**
 * B6 (MVP-7.1 review round 1): bot settings — deposit change, strategy version
 * change, delete (U5), plus display metadata (ticker, account name, version
 * number) that BotResponse itself does not carry.
 *
 * The backend contract R5: a version change and a delete are allowed only
 * while the bot is STOPPED and has no unclosed deal; the panel disables the
 * actions with a reason, and the backend 409 is still shown verbatim by the
 * caller.
 */
import { useEffect, useState } from "react";
import { api } from "../api";
import type {
  AccountInfo,
  BotResponse,
  DealResponse,
  InstrumentInfo,
  StrategyResponse,
  StrategyVersionOption,
} from "../types";
import { Button, ErrorBanner, Field, NumberInput, SelectInput } from "./FormControls";
import { ConfirmDialog } from "./ConfirmDialog";

export interface VersionMeta {
  strategyId: number;
  strategyName: string;
  version: number;
}

/** Display maps resolved from the catalog endpoints (never cached in the API). */
export interface BotDisplayMeta {
  /** strategy_version id -> {strategy, number} */
  versions: Map<number, VersionMeta>;
  /** local instrument id -> ticker (or FIGI) */
  instruments: Map<number, string>;
  /** local account id -> name (or broker id) */
  accounts: Map<number, string>;
  loading: boolean;
  error: string | null;
}

/** B6: load the display maps once per page (bot list / bot detail). */
export function useBotDisplayMeta(): BotDisplayMeta {
  const [meta, setMeta] = useState<BotDisplayMeta>({
    versions: new Map(),
    instruments: new Map(),
    accounts: new Map(),
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [strategies, instruments, accounts] = await Promise.all([
          api.get<StrategyResponse[]>("/api/strategies"),
          api.get<InstrumentInfo[]>("/api/instruments?active=true"),
          api.get<AccountInfo[]>("/api/accounts"),
        ]);
        const versions = new Map<number, VersionMeta>();
        await Promise.all(
          strategies.map(async (s) => {
            const list = await api.get<StrategyVersionOption[]>(
              `/api/strategies/${s.id}/versions`,
            );
            for (const v of list) {
              versions.set(v.id, { strategyId: s.id, strategyName: s.name, version: v.version });
            }
          }),
        );
        if (cancelled) return;
        setMeta({
          versions,
          instruments: new Map(
            instruments
              .filter((i) => i.id !== null)
              .map((i) => [i.id as number, i.ticker ?? i.figi]),
          ),
          accounts: new Map(
            accounts
              .filter((a) => a.id !== null)
              .map((a) => [a.id as number, a.name ?? a.account_id]),
          ),
          loading: false,
          error: null,
        });
      } catch (err) {
        if (!cancelled) {
          setMeta({
            versions: new Map(),
            instruments: new Map(),
            accounts: new Map(),
            loading: false,
            error: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return meta;
}

/** Human display helpers for the bot pages (B6). */
export function versionLabel(meta: BotDisplayMeta, versionId: number | null): string | null {
  if (versionId === null) return null;
  const v = meta.versions.get(versionId);
  return v ? `${v.strategyName} · версия ${v.version}` : null;
}

export function accountLabel(meta: BotDisplayMeta, accountId: number | null): string | null {
  if (accountId === null) return null;
  return meta.accounts.get(accountId) ?? `#${accountId}`;
}

export function instrumentLabel(meta: BotDisplayMeta, instrumentId: number | null): string | null {
  if (instrumentId === null) return null;
  return meta.instruments.get(instrumentId) ?? `#${instrumentId}`;
}

export function BotSettingsPanel(props: {
  bot: BotResponse;
  meta: BotDisplayMeta;
  onChanged: () => void;
  onError: (message: string) => void;
  /** Known open deal (detail page); when omitted, the panel fetches it lazily. */
  openDeal?: DealResponse | null;
  /** After a successful delete (detail page navigates away). */
  onDeleted?: () => void;
}) {
  const { bot, meta, onChanged, onError, openDeal, onDeleted } = props;
  const [open, setOpen] = useState(false);
  const [deal, setDeal] = useState<DealResponse | null | undefined>(
    openDeal !== undefined ? openDeal : undefined,
  );
  const [deposit, setDeposit] = useState<number | null>(
    bot.deposit === null ? null : Number(bot.deposit),
  );
  const [depositBusy, setDepositBusy] = useState(false);
  const [versionId, setVersionId] = useState("");
  const [versionBusy, setVersionBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const current =
    bot.strategy_version_id !== null ? meta.versions.get(bot.strategy_version_id) : undefined;
  const versionOptions =
    current === undefined
      ? []
      : [...meta.versions.entries()]
          .filter(([, v]) => v.strategyId === current.strategyId)
          .sort((a, b) => a[1].version - b[1].version)
          .map(([id, v]) => ({ value: String(id), label: `версия ${v.version}` }));

  // R5: version change / delete require STOPPED + no unclosed deal; fetch the
  // deal lazily when the caller (list page) does not know it.
  useEffect(() => {
    if (openDeal !== undefined || bot.status !== "STOPPED") return;
    let cancelled = false;
    void api
      .get<DealResponse | null>(`/api/bots/${bot.id}/deal`)
      .then((d) => {
        if (!cancelled) setDeal(d);
      })
      .catch((err) => {
        if (!cancelled) setDeal(null);
        if (!cancelled) onError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [bot.id, bot.status, openDeal, onError]);

  const lifecycleBlocked =
    bot.status !== "STOPPED"
      ? "Доступно только для остановленного бота."
      : deal === null
        ? null
        : "Есть незакрытая сделка — действие запрещено правилами R5.";
  const lifecycleDisabled = lifecycleBlocked !== null;

  const saveDeposit = async () => {
    if (deposit === null) {
      onError("Депозит — пустое поле при сохранении запрещено (нужно число > 0).");
      return;
    }
    setDepositBusy(true);
    try {
      await api.patch<BotResponse>(`/api/bots/${bot.id}`, { deposit });
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setDepositBusy(false);
    }
  };

  const clearDeposit = async () => {
    setDepositBusy(true);
    try {
      await api.patch<BotResponse>(`/api/bots/${bot.id}`, { deposit: null });
      setDeposit(null);
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setDepositBusy(false);
    }
  };

  const saveVersion = async () => {
    if (!versionId) return;
    setVersionBusy(true);
    try {
      await api.patch<BotResponse>(`/api/bots/${bot.id}`, {
        strategy_version_id: Number(versionId),
      });
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setVersionBusy(false);
    }
  };

  const doDelete = async () => {
    setConfirmDelete(false);
    setDeleteBusy(true);
    try {
      await api.delete<BotResponse>(`/api/bots/${bot.id}`);
      if (onDeleted) onDeleted();
      else onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <div className="rounded border border-zinc-800 bg-zinc-950/50 p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-zinc-400">Настройки бота</span>
        <Button variant="ghost" onClick={() => setOpen(!open)}>
          {open ? "Скрыть" : "Изменить (депозит, версия, удалить)"}
        </Button>
      </div>
      {meta.loading && !open ? (
        <p className="mt-1 text-xs text-zinc-500">Загрузка счёта, инструмента и версии…</p>
      ) : null}
      {open ? (
        <div className="mt-3 space-y-3">
          <ErrorBanner text={meta.error} />
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Field label="Депозит">
              <NumberInput
                value={deposit}
                disabled={depositBusy}
                placeholder="например, 100000"
                onChange={setDeposit}
              />
              <div className="mt-2 flex gap-2">
                <Button onClick={() => void saveDeposit()} disabled={depositBusy || deposit === null}>
                  Сохранить депозит
                </Button>
                {bot.deposit !== null ? (
                  <Button variant="ghost" onClick={() => void clearDeposit()} disabled={depositBusy}>
                    Убрать депозит
                  </Button>
                ) : null}
              </div>
            </Field>
            <Field label="Версия стратегии">
              <SelectInput
                value={versionId}
                onChange={setVersionId}
                allowEmpty
                emptyLabel={
                  current === undefined
                    ? "версии не загружены"
                    : `текущая: версия ${current.version}`
                }
                options={versionOptions}
                disabled={lifecycleDisabled || versionBusy || current === undefined}
              />
              <div className="mt-2 flex items-center gap-2">
                <Button
                  onClick={() => void saveVersion()}
                  disabled={versionBusy || !versionId || lifecycleDisabled}
                >
                  Сменить версию
                </Button>
                {lifecycleBlocked ? <span className="text-xs text-amber-400">{lifecycleBlocked}</span> : null}
              </div>
            </Field>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="danger" onClick={() => setConfirmDelete(true)} disabled={deleteBusy || lifecycleDisabled}>
              Удалить бота
            </Button>
            {lifecycleBlocked ? <span className="text-xs text-amber-400">{lifecycleBlocked}</span> : null}
          </div>
        </div>
      ) : null}
      <ConfirmDialog
        open={confirmDelete}
        title="Удалить бота?"
        message={
          <p>
            Бот «{bot.name}» будет удалён безвозвратно. Если у него есть незакрытая сделка —
            сервер отклонит удаление (409).
          </p>
        }
        confirmLabel="Удалить"
        danger
        onConfirm={doDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}
