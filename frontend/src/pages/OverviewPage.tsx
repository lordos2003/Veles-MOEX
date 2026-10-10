import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type {
  AccountInfo,
  CandleInfo,
  HealthResponse,
  InstrumentInfo,
  LastPriceInfo,
  OrderInfo,
  PositionInfo,
  TInvestStatus,
} from "../types";
import CandleChart from "../components/CandleChart";
import { Button, ErrorBanner, Loading, Section, SuccessBanner, TableWrap } from "../components/FormControls";
import { PageHeader } from "../components/PageHeader";
import { StatCard } from "../components/StatCard";
import { Stagger, StaggerItem } from "../components/ui/Motion";
import { InstrumentPicker } from "../components/InstrumentPicker";

/** U1 «Обзор»: T-Invest status, accounts, positions, market data with chart. */
export function OverviewPage() {
  const [backend, setBackend] = useState<"checking" | "ok" | "error">("checking");
  const [status, setStatus] = useState<TInvestStatus | null>(null);
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [positions, setPositions] = useState<PositionInfo[]>([]);
  const [orders, setOrders] = useState<OrderInfo[]>([]);
  const [deals, setDeals] = useState<{ deal_id: string; figi: string; side: string; quantity: string; price: string }[]>([]);
  const [instruments, setInstruments] = useState<InstrumentInfo[]>([]);
  const [selected, setSelected] = useState("");
  const [lastPrice, setLastPrice] = useState<LastPriceInfo | null>(null);
  const [candles, setCandles] = useState<CandleInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const h = await api.get<HealthResponse>("/api/health");
      setBackend(h.status === "ok" ? "ok" : "error");
    } catch {
      setBackend("error");
    }
    try {
      const [st, acc, inst, pos, ord, dl] = await Promise.all([
        api.get<TInvestStatus>("/api/tinvest/status"),
        api.get<AccountInfo[]>("/api/accounts"),
        api.get<InstrumentInfo[]>("/api/instruments?active=true"),
        api.get<PositionInfo[]>("/api/positions").catch(() => [] as PositionInfo[]),
        api.get<OrderInfo[]>("/api/orders").catch(() => [] as OrderInfo[]),
        api.get<{ deal_id: string; figi: string; side: string; quantity: string; price: string }[]>("/api/deals").catch(() => []),
      ]);
      setStatus(st);
      setAccounts(acc);
      setInstruments(inst);
      setPositions(pos);
      setOrders(ord);
      setDeals(dl);
      if (inst.length > 0) setSelected((prev) => (prev && inst.some((i) => i.figi === prev) ? prev : inst[0].figi));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const syncInstruments = async () => {
    setSyncing(true);
    setError(null);
    setSuccess(null);
    try {
      const data = await api.post<{ synced: number }>("/api/instruments/sync?kind=share");
      await load();
      setSuccess(`Синхронизировано инструментов: ${data.synced}`);
    } catch (err) {
      setSuccess(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  };

  const selectInstrument = useCallback((figi: string) => {
    setSelected(figi);
  }, []);

  const loadMarket = useCallback(async (figi: string) => {
    if (!figi) return;
    setError(null);
    try {
      const to = new Date().toISOString();
      const from = new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString();
      const [priceRes, candleRes] = await Promise.all([
        fetch(`/api/market-data/${figi}/last-price`),
        fetch(`/api/market-data/${figi}/candles?timeframe=1d&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),
      ]);
      if (priceRes.ok) setLastPrice((await priceRes.json()) as LastPriceInfo);
      if (candleRes.ok) setCandles((await candleRes.json()) as CandleInfo[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    if (selected) void loadMarket(selected);
  }, [selected, loadMarket]);

  const backendLabel =
    backend === "ok" ? "подключен" : backend === "error" ? "недоступен" : "проверка…";
  const statusLabel =
    status?.status === "connected"
      ? "Подключено"
      : status?.status === "not_configured"
        ? "Не настроено"
        : "Отключено";
  const sel = instruments.find((i) => i.figi === selected);

  const statusTone = status?.status === "connected" ? "success" : status?.status === "not_configured" ? "warning" : "error";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Обзор"
        description="Подключение к T-Invest, счета брокера, позиции и рыночные данные."
      />
      <Stagger className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StaggerItem>
          <StatCard label="T-Invest" value={statusLabel} hint={`Backend: ${backendLabel}`} loading={!loaded} tone={statusTone} />
        </StaggerItem>
        <StaggerItem>
          <StatCard label="Счета" value={accounts.length} hint={`сохранено: ${accounts.filter((a) => a.is_saved).length}`} loading={!loaded} />
        </StaggerItem>
        <StaggerItem>
          <StatCard label="Позиции" value={positions.length} hint={`заявок: ${orders.length} · сделок: ${deals.length}`} loading={!loaded} />
        </StaggerItem>
        <StaggerItem>
          <StatCard label="Инструменты" value={instruments.length} hint="активные, в локальной базе" loading={!loaded} />
        </StaggerItem>
      </Stagger>

      <SuccessBanner text={success} />
      <ErrorBanner text={error} />
      <Section title="T-Invest">
        <p className="text-sm text-text-muted">Backend: {backendLabel}</p>
        <p className="text-sm">
          <span
            className={
              status?.status === "connected"
                ? "text-emerald-400"
                : status?.status === "not_configured"
                  ? "text-amber-400"
                  : "text-red-400"
            }
          >
            {statusLabel}
          </span>
          {status ? ` — ${status.message}` : ""}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" onClick={() => void load()}>
            Загрузить
          </Button>
          <Button variant="ghost" onClick={() => void syncInstruments()} disabled={syncing}>
            {syncing ? "Синхронизация…" : "Синхронизировать инструменты"}
          </Button>
        </div>
      </Section>

      <Section title="Счета брокера">
        {accounts.length === 0 ? (
          <p className="text-sm text-text-muted">Счета не загружены (нужен TINVEST_TOKEN).</p>
        ) : (
          <ul className="grid gap-3 text-sm md:grid-cols-2">
            {accounts.map((acc) => (
              <li key={acc.account_id} className="rounded-control border border-zinc-800 bg-zinc-950/40 p-3">
                <span className="font-medium">{acc.name ?? acc.account_id}</span>{" "}
                <span className="break-all text-zinc-400">{acc.status ?? ""}</span>
                {acc.is_saved ? (
                  <span className="ml-2 rounded-full bg-emerald-900/50 px-2 py-0.5 text-xs text-emerald-300">
                    сохранён
                  </span>
                ) : null}
                <span className="num mt-1 block break-words text-xs text-text-muted">
                  {acc.account_type ?? ""} · {acc.currency} · свободно:{" "}
                  {acc.portfolio_available ? acc.available_cash : "—"} · эквити:{" "}
                  {acc.portfolio_available ? acc.equity : "—"}
                  {acc.portfolio_available === false ? (
                    <span className="ml-1 rounded-full bg-amber-900/50 px-2 py-0.5 text-xs text-amber-300">
                      портфель недоступен
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Позиции">
        {positions.length === 0 ? (
          <p className="text-sm text-text-muted">Открытых позиций нет.</p>
        ) : (
          <TableWrap label="Таблица позиций">
            <table className="w-full min-w-[28rem] text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-800 text-xs uppercase tracking-[0.06em] text-text-muted">
                  <th className="py-2 pr-3 font-medium">тикер</th>
                  <th className="px-3 text-right font-medium">объём</th>
                  <th className="px-3 text-right font-medium">средняя</th>
                  <th className="px-3 text-right font-medium">цена</th>
                  <th className="pl-3 text-right font-medium">PnL</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.figi} className="border-b border-zinc-800/60 transition-colors hover:bg-zinc-800/40">
                    <td className="py-2.5 pr-3 font-medium">{p.ticker ?? p.figi}</td>
                    <td className="num px-3 text-right">{p.quantity}</td>
                    <td className="num px-3 text-right">{p.average_price}</td>
                    <td className="num px-3 text-right">{p.current_price}</td>
                    <td
                      className={
                        "num pl-3 text-right " +
                        (p.unrealized_pnl.trim().startsWith("-") ? "text-error" : "text-success")
                      }
                    >
                      {p.unrealized_pnl}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Section>

      <Section title="Рынок">
        {instruments.length === 0 ? (
          <p className="text-sm text-text-muted">
            Инструменты пусты. Нажмите «Синхронизировать инструменты».
          </p>
        ) : (
          <>
            <InstrumentPicker
              instruments={instruments}
              selectedFigi={selected}
              onSelect={selectInstrument}
              listId="market-search-results"
            />
            {lastPrice ? (
              <p className="text-sm">
                Последняя цена: <span className="num font-medium">{lastPrice.price}</span>
              </p>
            ) : null}
            <CandleChart candles={candles} />
            {sel ? (
              <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {[
                  ["Лот", sel.lot_size ?? "—"],
                  ["Шаг цены", sel.tick_size ?? "—"],
                  ["Статус", sel.trading_status],
                  ["Биржа", sel.exchange ?? "—"],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-control border border-zinc-800 bg-zinc-950/40 px-3 py-2">
                    <dt className="text-xs text-text-muted">{k}</dt>
                    <dd className="num mt-0.5 break-words text-sm">{v}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </>
        )}
      </Section>

      <Section title="Заявки и сделки (только чтение)">
        {orders.length === 0 && deals.length === 0 ? (
          <Loading text="Заявок и сделок нет." />
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div>
              <p className="mb-1 text-xs text-text-muted">Заявки</p>
              {orders.map((o) => (
                <p key={o.order_id} className="num break-words text-xs">
                  {o.ticker ?? o.figi} · {o.side ?? "—"} · {o.status} · {o.requested_quantity}/
                  {o.executed_quantity}
                </p>
              ))}
            </div>
            <div>
              <p className="mb-1 text-xs text-text-muted">Сделки</p>
              {deals.map((d) => (
                <p key={d.deal_id} className="num break-words text-xs">
                  {d.figi} · {d.side} · {d.quantity} @ {d.price}
                </p>
              ))}
            </div>
          </div>
        )}
      </Section>
    </div>
  );
}
