import { useCallback, useEffect, useMemo, useState } from "react";
import type { KeyboardEvent } from "react";
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
import { Button, ErrorBanner, Loading, Section, SuccessBanner } from "../components/FormControls";
import { filterInstruments } from "../lib/instrumentSearch";

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

  // U2: live search over the already-loaded instruments (no per-keystroke
  // broker requests) — case-insensitive substring on ticker / name / FIGI.
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);

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

  const filtered = useMemo(() => filterInstruments(search, instruments), [search, instruments]);

  const selectInstrument = useCallback(
    (figi: string) => {
      const inst = instruments.find((i) => i.figi === figi);
      setSelected(figi);
      setSearch(inst ? `${inst.ticker} — ${inst.name ?? ""}` : "");
      setSearchOpen(false);
    },
    [instruments],
  );

  const onSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!searchOpen) {
        setSearchOpen(true);
        return;
      }
      setHighlight((h) => Math.min(h + 1, Math.max(filtered.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const pick = filtered[highlight];
      if (searchOpen && pick) selectInstrument(pick.figi);
    } else if (event.key === "Escape") {
      setSearchOpen(false);
    }
  };

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

  return (
    <div className="space-y-4">
      <SuccessBanner text={success} />
      <ErrorBanner text={error} />
      <Section title="T-Invest">
        <p className="text-sm text-zinc-500">Backend: {backendLabel}</p>
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
        <div className="flex gap-2">
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
          <p className="text-sm text-zinc-500">Счета не загружены (нужен TINVEST_TOKEN).</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {accounts.map((acc) => (
              <li key={acc.account_id} className="rounded bg-zinc-900 p-2">
                <span className="font-medium">{acc.name ?? acc.account_id}</span>{" "}
                <span className="text-zinc-400">{acc.status ?? ""}</span>
                {acc.is_saved ? (
                  <span className="ml-2 rounded bg-emerald-900/50 px-1.5 py-0.5 text-xs text-emerald-300">
                    сохранён
                  </span>
                ) : null}
                <span className="block text-xs text-zinc-500">
                  {acc.account_type ?? ""} · {acc.currency} · свободно:{" "}
                  {acc.portfolio_available ? acc.available_cash : "—"} · эквити:{" "}
                  {acc.portfolio_available ? acc.equity : "—"}
                  {acc.portfolio_available === false ? (
                    <span className="ml-1 rounded bg-amber-900/50 px-1.5 py-0.5 text-xs text-amber-300">
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
          <p className="text-sm text-zinc-500">Открытых позиций нет.</p>
        ) : (
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500">
                <th className="py-1">тикер</th>
                <th>объём</th>
                <th>средняя</th>
                <th>цена</th>
                <th>PnL</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.figi} className="border-b border-zinc-900">
                  <td className="py-1">{p.ticker ?? p.figi}</td>
                  <td>{p.quantity}</td>
                  <td>{p.average_price}</td>
                  <td>{p.current_price}</td>
                  <td>{p.unrealized_pnl}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Рынок">
        {instruments.length === 0 ? (
          <p className="text-sm text-zinc-500">
            Инструменты пусты. Нажмите «Синхронизировать инструменты».
          </p>
        ) : (
          <>
            <div className="relative">
              <input
                className="w-full rounded border border-zinc-700 bg-zinc-900 p-2 text-sm"
                placeholder="Поиск по тикеру, названию или FIGI…"
                value={search}
                role="combobox"
                aria-expanded={searchOpen}
                aria-controls="market-search-results"
                onChange={(e) => {
                  setSearch(e.target.value);
                  setSearchOpen(true);
                  setHighlight(0);
                }}
                onFocus={() => setSearchOpen(true)}
                onBlur={() => setSearchOpen(false)}
                onKeyDown={onSearchKeyDown}
              />
              {searchOpen ? (
                <div
                  id="market-search-results"
                  className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded border border-zinc-700 bg-zinc-900"
                >
                  <p className="px-3 py-1 text-xs text-zinc-500">
                    Найдено: {filtered.length} из {instruments.length}
                  </p>
                  {filtered.length === 0 ? (
                    <p className="px-3 py-2 text-sm text-zinc-500">Ничего не найдено</p>
                  ) : (
                    <ul>
                      {filtered.map((inst, idx) => (
                        <li key={inst.figi}>
                          <button
                            type="button"
                            className={`block w-full px-3 py-1.5 text-left text-sm ${
                              idx === highlight ? "bg-zinc-800" : ""
                            } ${inst.figi === selected ? "text-emerald-400" : ""}`}
                            onMouseDown={(e) => {
                              e.preventDefault();
                              selectInstrument(inst.figi);
                            }}
                          >
                            {inst.ticker} — {inst.name}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}
            </div>
            {lastPrice ? (
              <p className="text-sm">
                Последняя цена: <span className="font-medium">{lastPrice.price}</span>
              </p>
            ) : null}
            <CandleChart candles={candles} />
            {sel ? (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded bg-zinc-900 p-3 text-sm lg:grid-cols-4">
                <dt className="text-zinc-500">Лот</dt>
                <dd>{sel.lot_size ?? "—"}</dd>
                <dt className="text-zinc-500">Шаг цены</dt>
                <dd>{sel.tick_size ?? "—"}</dd>
                <dt className="text-zinc-500">Статус</dt>
                <dd>{sel.trading_status}</dd>
                <dt className="text-zinc-500">Биржа</dt>
                <dd>{sel.exchange ?? "—"}</dd>
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
              <p className="mb-1 text-xs text-zinc-500">Заявки</p>
              {orders.map((o) => (
                <p key={o.order_id} className="text-xs">
                  {o.ticker ?? o.figi} · {o.side ?? "—"} · {o.status} · {o.requested_quantity}/
                  {o.executed_quantity}
                </p>
              ))}
            </div>
            <div>
              <p className="mb-1 text-xs text-zinc-500">Сделки</p>
              {deals.map((d) => (
                <p key={d.deal_id} className="text-xs">
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
