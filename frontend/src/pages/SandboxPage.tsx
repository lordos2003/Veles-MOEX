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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Песочница и счета</h2>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => void syncAccounts()} disabled={busy}>
            Синхронизировать счета
          </Button>
          <Button onClick={() => void createSandboxAccount()} disabled={busy}>
            + Открыть песочничный счёт
          </Button>
        </div>
      </div>
      <SuccessBanner text={success} />
      <ErrorBanner text={error} />

      {!accounts ? (
        <Loading />
      ) : accounts.length === 0 ? (
        <p className="text-sm text-zinc-500">Счетов нет. Откройте песочничный счёт или синхронизируйте брокерские.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {accounts.map((a) => (
            <button
              key={a.account_id}
              onClick={() => void openAccount(a.account_id)}
              className={`rounded-lg border p-4 text-left hover:border-zinc-500 ${
                a.account_id === selectedId ? "border-emerald-600 bg-zinc-900/70" : "border-zinc-800 bg-zinc-900/40"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-zinc-100">{a.name ?? a.account_id}</span>
                {a.is_saved ? (
                  <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-emerald-300">сохранён</span>
                ) : (
                  <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">не сохранён</span>
                )}
              </div>
              <div className="mt-1 grid grid-cols-2 gap-1 text-xs text-zinc-500">
                <span>ID: {a.account_id}</span>
                <span>Брокер: {a.broker}</span>
                <span>Валюта: {a.currency}</span>
                <span>Тип: {a.account_type ?? "—"}</span>
                <span>Баланс: {a.available_cash}</span>
                <span>Капитал: {a.equity}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {selected ? (
        <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-medium text-zinc-200">{selected.name ?? selected.account_id}</h3>
            <button
              className="text-xs text-red-400 hover:underline"
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
            <h4 className="mb-2 text-sm font-medium text-zinc-300">Позиции</h4>
            {positions.length === 0 ? (
              <p className="text-sm text-zinc-500">Нет открытых позиций.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-500">
                      <th className="py-1 pr-3">FIGI</th>
                      <th className="pr-3">Тикер</th>
                      <th className="pr-3">Кол-во</th>
                      <th className="pr-3">Средняя цена</th>
                      <th className="pr-3">Текущая цена</th>
                      <th className="pr-3">Нереализ. PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p, i) => (
                      <tr key={i} className="border-b border-zinc-900">
                        <td className="py-1 pr-3">{p.figi}</td>
                        <td className="pr-3">{p.ticker ?? "—"}</td>
                        <td className="pr-3">{p.quantity}</td>
                        <td className="pr-3 font-mono">{p.average_price}</td>
                        <td className="pr-3 font-mono">{p.current_price}</td>
                        <td className="pr-3 font-mono">{p.unrealized_pnl}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <h4 className="mb-2 text-sm font-medium text-zinc-300">Заявки</h4>
            {orders.length === 0 ? (
              <p className="text-sm text-zinc-500">Заявок нет.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-500">
                      <th className="py-1 pr-3">Заявка</th>
                      <th className="pr-3">FIGI</th>
                      <th className="pr-3">Сторона</th>
                      <th className="pr-3">Статус</th>
                      <th className="pr-3">Кол-во</th>
                      <th className="pr-3">Цена</th>
                      <th className="pr-3">Отклонено</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((o) => (
                      <tr key={o.order_id} className="border-b border-zinc-900">
                        <td className="py-1 pr-3">{o.order_id}</td>
                        <td className="pr-3">{o.figi ?? "—"}</td>
                        <td className="pr-3">{o.side ?? "—"}</td>
                        <td className="pr-3">{ORDER_STATUS_LABELS[o.status] ?? o.status}</td>
                        <td className="pr-3">{o.executed_quantity}/{o.requested_quantity}</td>
                        <td className="pr-3 font-mono">{o.price ?? "—"}</td>
                        <td className="pr-3 text-red-400">{o.reject_info ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <h4 className="mb-2 text-sm font-medium text-zinc-300">Сделки</h4>
            {deals.length === 0 ? (
              <p className="text-sm text-zinc-500">Сделок нет.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-500">
                      <th className="py-1 pr-3">Сделка</th>
                      <th className="pr-3">FIGI</th>
                      <th className="pr-3">Сторона</th>
                      <th className="pr-3">Кол-во</th>
                      <th className="pr-3">Цена</th>
                      <th className="pr-3">Комиссия</th>
                      <th className="pr-3">Время</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deals.map((d) => (
                      <tr key={d.deal_id} className="border-b border-zinc-900">
                        <td className="py-1 pr-3">{d.deal_id}</td>
                        <td className="pr-3">{d.figi}</td>
                        <td className="pr-3">{d.side === "BUY" ? "Покупка" : "Продажа"}</td>
                        <td className="pr-3">{d.quantity}</td>
                        <td className="pr-3 font-mono">{d.price}</td>
                        <td className="pr-3 font-mono">{d.commission}</td>
                        <td className="pr-3">{d.happened_at ? new Date(d.happened_at).toLocaleString("ru-RU") : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      ) : (
        <p className="text-xs text-zinc-500">Выберите счёт, чтобы увидеть позиции, заявки и сделки.</p>
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
