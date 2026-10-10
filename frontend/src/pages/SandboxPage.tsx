import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type {
  AccountInfo,
  DealInfo,
  OrderInfo,
  PositionInfo,
  SandboxPayInResponse,
  SyncResponse,
} from "../types";
import { Button, ErrorBanner, Field, Loading, SelectInput, SuccessBanner, TextInput } from "../components/FormControls";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";
import { ORDER_STATUS_LABELS } from "../lib/labels";

export function SandboxPage() {
  const [accounts, setAccounts] = useState<AccountInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [selectedId, setSelectedId] = useState("");
  const [positions, setPositions] = useState<PositionInfo[]>([]);
  const [orders, setOrders] = useState<OrderInfo[]>([]);
  const [deals, setDeals] = useState<DealInfo[]>([]);

  const [payInAmount, setPayInAmount] = useState("");
  const [payInCurrency, setPayInCurrency] = useState("RUB");
  const [closing, setClosing] = useState(false);

  const loadAccounts = useCallback(async () => {
    setError(null);
    try {
      setAccounts(await api.get<AccountInfo[]>("/api/accounts"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  const selected = accounts?.find((a) => a.account_id === selectedId) ?? null;

  const openAccount = async (accountId: string) => {
    setSelectedId(accountId);
    setSuccess(null);
    try {
      const [p, o, d] = await Promise.all([
        api.get<PositionInfo[]>(`/api/positions?account_id=${encodeURIComponent(accountId)}`),
        api.get<OrderInfo[]>(`/api/orders?account_id=${encodeURIComponent(accountId)}`),
        api.get<DealInfo[]>(`/api/deals?account_id=${encodeURIComponent(accountId)}`),
      ]);
      setPositions(p);
      setOrders(o);
      setDeals(d);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const createSandboxAccount = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await api.post<{ account_id: string }>("/api/sandbox/accounts");
      await loadAccounts();
      await openAccount(res.account_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const payIn = async () => {
    if (!selected || !payInAmount.trim()) return;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await api.post<SandboxPayInResponse>(
        `/api/sandbox/accounts/${encodeURIComponent(selected.account_id)}/pay-in`,
        { account_id: selected.account_id, amount: payInAmount.trim(), currency: payInCurrency.trim() },
      );
      await loadAccounts();
      await openAccount(selected.account_id);
      setPayInAmount("");
      setSuccess(`Пополнение выполнено, баланс: ${res.balance}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const closeSandboxAccount = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      await api.delete<{ account_id: string }>(
        `/api/sandbox/accounts/${encodeURIComponent(selected.account_id)}`,
      );
      setClosing(false);
      setSelectedId("");
      setPositions([]);
      setOrders([]);
      setDeals([]);
      await loadAccounts();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const syncAccounts = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await api.post<SyncResponse>("/api/accounts/sync");
      await loadAccounts();
      setSuccess(`Синхронизировано счетов: ${res.synced}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Песочница и счета"
        description="Тестовые счета T-Invest: пополнение, позиции, заявки и сделки."
        actions={
          <>
            <Button variant="ghost" onClick={() => void syncAccounts()} disabled={busy}>
              Синхронизировать счета
            </Button>
            <Button onClick={() => void createSandboxAccount()} disabled={busy}>
              + Открыть песочничный счёт
            </Button>
          </>
        }
      />
      <SuccessBanner text={success} />
      <ErrorBanner text={error} />

      {!accounts ? (
        <Loading />
      ) : accounts.length === 0 ? (
        <p className="text-sm text-text-muted">Счетов нет. Откройте песочничный счёт или синхронизируйте брокерские.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {accounts.map((a) => (
            <button
              key={a.account_id}
              onClick={() => void openAccount(a.account_id)}
              className={`rounded-card border p-4 text-left shadow-card transition-[border-color,background-color,box-shadow] duration-(--duration-fast) hover:border-zinc-600 ${
                a.account_id === selectedId
                  ? "border-accent-bright/60 bg-surface shadow-glow"
                  : "border-zinc-800 bg-surface/60"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-zinc-100">{a.name ?? a.account_id}</span>
                {a.is_saved ? (
                  <span className="rounded-full bg-emerald-900/40 px-2 py-0.5 text-xs text-emerald-300">сохранён</span>
                ) : (
                  <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">не сохранён</span>
                )}
              </div>
              <div className="num mt-2 grid grid-cols-1 gap-1 break-words text-xs text-text-muted sm:grid-cols-2">
                <span>ID: {a.account_id}</span>
                <span>Брокер: {a.broker}</span>
                <span>Валюта: {a.currency}</span>
                <span>Тип: {a.account_type ?? "—"}</span>
                <span>Баланс: {a.portfolio_available ? a.available_cash : "—"}</span>
                <span>Капитал: {a.portfolio_available ? a.equity : "—"}</span>
                {a.portfolio_available === false ? (
                  <span className="text-amber-400">портфель недоступен</span>
                ) : null}
              </div>
            </button>
          ))}
        </div>
      )}

      {selected ? (
        <div className="space-y-4 rounded-card border border-zinc-800 bg-surface/60 p-4 shadow-card sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-medium text-text">{selected.name ?? selected.account_id}</h3>
            <button
              className="inline-flex min-h-8 items-center rounded-control px-2 text-xs text-red-400 hover:bg-red-950/40 hover:underline"
              onClick={() => setClosing(true)}
              disabled={busy}
            >
              Закрыть песочничный счёт
            </button>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Сумма пополнения">
              <TextInput value={payInAmount} onChange={setPayInAmount} placeholder="например, 1000000" />
            </Field>
            <Field label="Валюта">
              <SelectInput
                value={payInCurrency}
                onChange={setPayInCurrency}
                allowEmpty={false}
                options={[...new Set([...selected.currencies, "RUB", "USD"])].map((c) => ({ value: c, label: c }))}
              />
            </Field>
          </div>
          <Button onClick={() => void payIn()} disabled={busy || !payInAmount.trim()}>
            Пополнить
          </Button>

          <section>
            <h4 className="mb-2 text-sm font-medium text-text-secondary">Позиции</h4>
            {positions.length === 0 ? (
              <p className="text-sm text-text-muted">Нет открытых позиций.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>FIGI</th>
                      <th>Тикер</th>
                      <th>Кол-во</th>
                      <th>Средняя цена</th>
                      <th>Текущая цена</th>
                      <th>Нереализ. PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p, i) => (
                      <tr key={i}>
                        <td>{p.figi}</td>
                        <td>{p.ticker ?? "—"}</td>
                        <td>{p.quantity}</td>
                        <td className="num">{p.average_price}</td>
                        <td className="num">{p.current_price}</td>
                        <td className="num">{p.unrealized_pnl}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <h4 className="mb-2 text-sm font-medium text-text-secondary">Заявки</h4>
            {orders.length === 0 ? (
              <p className="text-sm text-text-muted">Заявок нет.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Заявка</th>
                      <th>FIGI</th>
                      <th>Сторона</th>
                      <th>Статус</th>
                      <th>Кол-во</th>
                      <th>Цена</th>
                      <th>Отклонено</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((o) => (
                      <tr key={o.order_id}>
                        <td>{o.order_id}</td>
                        <td>{o.figi ?? "—"}</td>
                        <td>{o.side ?? "—"}</td>
                        <td>{ORDER_STATUS_LABELS[o.status] ?? o.status}</td>
                        <td>{o.executed_quantity}/{o.requested_quantity}</td>
                        <td className="num">{o.price ?? "—"}</td>
                        <td className="text-error">{o.reject_info ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <h4 className="mb-2 text-sm font-medium text-text-secondary">Сделки</h4>
            {deals.length === 0 ? (
              <p className="text-sm text-text-muted">Сделок нет.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Сделка</th>
                      <th>FIGI</th>
                      <th>Сторона</th>
                      <th>Кол-во</th>
                      <th>Цена</th>
                      <th>Комиссия</th>
                      <th>Время</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deals.map((d) => (
                      <tr key={d.deal_id}>
                        <td>{d.deal_id}</td>
                        <td>{d.figi}</td>
                        <td>{d.side === "BUY" ? "Покупка" : "Продажа"}</td>
                        <td>{d.quantity}</td>
                        <td className="num">{d.price}</td>
                        <td className="num">{d.commission}</td>
                        <td>{d.happened_at ? new Date(d.happened_at).toLocaleString("ru-RU") : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      ) : (
        <p className="text-xs text-text-muted">Выберите счёт, чтобы увидеть позиции, заявки и сделки.</p>
      )}

      <ConfirmDialog
        open={closing}
        title="Закрыть песочничный счёт?"
        message={<p>Счёт <b>{selected?.account_id}</b> будет закрыт. Это действие необратимо.</p>}
        confirmLabel="Закрыть"
        danger
        onConfirm={() => void closeSandboxAccount()}
        onCancel={() => setClosing(false)}
      />
    </div>
  );
}
