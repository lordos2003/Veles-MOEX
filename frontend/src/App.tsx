import { useCallback, useEffect, useState } from "react";
import CandleChart from "./components/CandleChart";

type BackendStatus = "checking" | "ok" | "error";

interface HealthResponse {
  status: string;
}

interface TInvestStatus {
  status: string;
  message: string;
}

interface Account {
  account_id: string;
  name: string | null;
  status: string | null;
  account_type: string | null;
  currency: string;
  available_cash: string;
  equity: string;
}

interface Position {
  account_id: string;
  figi: string;
  ticker: string | null;
  instrument_type: string | null;
  quantity: string;
  average_price: string;
  current_price: string;
  current_value: string;
  unrealized_pnl: string;
  currency: string | null;
}

interface Order {
  order_id: string;
  account_id: string | null;
  figi: string | null;
  ticker: string | null;
  status: string;
  type: string | null;
  side: string | null;
  requested_quantity: string;
  executed_quantity: string;
  price: string | null;
  currency: string | null;
}

interface Deal {
  deal_id: string;
  account_id: string | null;
  figi: string;
  side: string;
  quantity: string;
  price: string;
  commission: string;
  currency: string | null;
  happened_at: string | null;
}

interface Instrument {
  figi: string;
  ticker: string | null;
  name: string | null;
  instrument_type: string | null;
  currency: string | null;
  lot_size: number | null;
  tick_size: string | null;
  trading_status: string;
  exchange: string | null;
  is_active: boolean;
}

interface LastPrice {
  figi: string;
  ticker: string | null;
  price: string;
  timestamp: string | null;
}

interface Candle {
  figi: string;
  timeframe: string;
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
}

function App() {
  const [backend, setBackend] = useState<BackendStatus>("checking");
  const [status, setStatus] = useState<TInvestStatus | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(false);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [lastPrice, setLastPrice] = useState<LastPrice | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch("/api/health");
        if (res.ok) {
          const d: HealthResponse = await res.json();
          if (!cancelled) setBackend(d.status === "ok" ? "ok" : "error");
        }
      } catch {
        if (!cancelled) setBackend("error");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadIntegration = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const [statusRes, accountsRes, instrumentsRes, positionsRes, ordersRes, dealsRes] =
        await Promise.all([
          fetch("/api/tinvest/status"),
          fetch("/api/accounts"),
          fetch("/api/instruments"),
          fetch("/api/positions"),
          fetch("/api/orders"),
          fetch("/api/deals"),
        ]);
      const statusData: TInvestStatus = await statusRes.json();
      setStatus(statusData);
      setAccounts(await accountsRes.json());
      const instrumentsData: Instrument[] = await instrumentsRes.json();
      setInstruments(instrumentsData);
      setPositions(positionsRes.ok ? await positionsRes.json() : []);
      setOrders(ordersRes.ok ? await ordersRes.json() : []);
      setDeals(dealsRes.ok ? await dealsRes.json() : []);
      if (instrumentsData.length > 0) setSelected(instrumentsData[0].figi);
    } catch {
      setError("Не удалось загрузить данные интеграции");
    } finally {
      setLoading(false);
    }
  }, []);

  const syncInstruments = useCallback(async () => {
    setSyncing(true);
    setError(null);
    try {
      const res = await fetch("/api/instruments/sync?kind=share", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { synced: number };
      await loadIntegration();
      setError(`Синхронизировано инструментов: ${data.synced}`);
    } catch (err) {
      setError(`Синхронизация не удалась: ${(err as Error).message}`);
    } finally {
      setSyncing(false);
    }
  }, [loadIntegration]);

  const loadMarketData = useCallback(async (figi: string) => {
    if (!figi) return;
    setError(null);
    try {
      const to = new Date().toISOString();
      const from = new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString();
      const [priceRes, candleRes] = await Promise.all([
        fetch(`/api/market-data/${figi}/last-price`),
        fetch(`/api/market-data/${figi}/candles?timeframe=1d&from=${from}&to=${to}&limit=30`),
      ]);
      if (priceRes.ok) setLastPrice(await priceRes.json());
      if (candleRes.ok) setCandles(await candleRes.json());
    } catch {
      setError("Не удалось загрузить рыночные данные");
    }
  }, []);

  useEffect(() => {
    if (selected) loadMarketData(selected);
  }, [selected, loadMarketData]);

  const backendColor =
    backend === "ok" ? "text-green-500" : backend === "error" ? "text-red-500" : "text-yellow-500";
  const statusLabel =
    status?.status === "connected"
      ? "Connected"
      : status?.status === "not_configured"
        ? "Not configured"
        : "Disconnected";
  const statusColor =
    status?.status === "connected"
      ? "text-green-500"
      : status?.status === "not_configured"
        ? "text-yellow-500"
        : "text-red-500";

  const sel = instruments.find((i) => i.figi === selected);

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <header className="flex items-center justify-between border-b border-zinc-800 pb-4">
          <h1 className="text-2xl font-semibold tracking-tight">Veles-MOEX</h1>
          <span className={backendColor + " text-sm"}>
            Backend: {backend === "ok" ? "подключен" : backend === "error" ? "недоступен" : "проверка..."}
          </span>
        </header>

        <section className="mt-6">
          <h2 className="text-lg font-medium">T-Invest Connection</h2>
          <p className={statusColor + " mt-1 text-sm"}>
            {statusLabel} {status ? `— ${status.message}` : ""}
          </p>
          <div className="mt-2 flex gap-2">
            <button
              onClick={loadIntegration}
              className="rounded border border-zinc-700 px-3 py-1 text-sm hover:bg-zinc-800"
            >
              Загрузить
            </button>
            <button
              onClick={syncInstruments}
              disabled={syncing}
              className="rounded border border-zinc-700 px-3 py-1 text-sm hover:bg-zinc-800 disabled:opacity-50"
            >
              {syncing ? "Синхронизация…" : "Синхронизировать инструменты"}
            </button>
          </div>
        </section>

        {error && <p className="mt-4 text-sm text-amber-500">{error}</p>}

        <section className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2">
          <div>
            <h2 className="text-lg font-medium">Accounts</h2>
            <ul className="mt-2 space-y-1 text-sm">
              {accounts.map((acc) => (
                <li key={acc.account_id} className="rounded bg-zinc-900 p-2">
                  <span className="font-medium">{acc.name ?? acc.account_id}</span>{" "}
                  <span className="text-zinc-400">{acc.status ?? ""}</span>
                  <span className="block text-xs text-zinc-500">
                    {acc.account_type ?? ""} · {acc.currency}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h2 className="text-lg font-medium">Instruments</h2>
            <select
              className="mt-2 w-full rounded border border-zinc-700 bg-zinc-900 p-2 text-sm"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              {instruments.map((inst) => (
                <option key={inst.figi} value={inst.figi}>
                  {inst.ticker} — {inst.name} ({inst.instrument_type} / {inst.currency})
                </option>
              ))}
            </select>

            {sel && (
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 rounded bg-zinc-900 p-3 text-sm">
                <dt className="text-zinc-500">Ticker</dt>
                <dd>{sel.ticker}</dd>
                <dt className="text-zinc-500">Name</dt>
                <dd>{sel.name}</dd>
                <dt className="text-zinc-500">Type</dt>
                <dd>{sel.instrument_type}</dd>
                <dt className="text-zinc-500">Currency</dt>
                <dd>{sel.currency}</dd>
                <dt className="text-zinc-500">Lot</dt>
                <dd>{sel.lot_size ?? "—"}</dd>
                <dt className="text-zinc-500">Tick</dt>
                <dd>{sel.tick_size ?? "—"}</dd>
                <dt className="text-zinc-500">Trading status</dt>
                <dd>{sel.trading_status}</dd>
                <dt className="text-zinc-500">Exchange</dt>
                <dd>{sel.exchange ?? "—"}</dd>
                <dt className="text-zinc-500">Active</dt>
                <dd>{sel.is_active ? "yes" : "no"}</dd>
              </dl>
            )}

            {instruments.length === 0 && (
              <p className="mt-2 text-xs text-zinc-500">
                Инструменты пусты. Нажмите «Синхронизировать инструменты».
              </p>
            )}
          </div>
        </section>

        <section className="mt-6">
          <h2 className="text-lg font-medium">Broker Data (read-only)</h2>
          {loading && <p className="mt-2 text-sm text-zinc-500">Загрузка…</p>}
          {!loading &&
            (positions.length === 0 && orders.length === 0 && deals.length === 0 ? (
              <p className="mt-2 text-xs text-zinc-500">Нет данных (нужен TINVEST_TOKEN).</p>
            ) : (
              <div className="mt-3 grid grid-cols-1 gap-6 lg:grid-cols-3">
                <div>
                  <h3 className="text-sm font-medium text-zinc-400">Positions</h3>
                  <table className="mt-1 w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-zinc-800 text-zinc-500">
                        <th className="py-1">ticker</th>
                        <th>qty</th>
                        <th>avg</th>
                        <th>cur</th>
                        <th>pnl</th>
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
                </div>
                <div>
                  <h3 className="text-sm font-medium text-zinc-400">Orders</h3>
                  <table className="mt-1 w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-zinc-800 text-zinc-500">
                        <th className="py-1">id</th>
                        <th>status</th>
                        <th>side</th>
                        <th>qty</th>
                        <th>filled</th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.map((o) => (
                        <tr key={o.order_id} className="border-b border-zinc-900">
                          <td className="py-1">{o.order_id}</td>
                          <td>{o.status}</td>
                          <td>{o.side ?? "—"}</td>
                          <td>{o.requested_quantity}</td>
                          <td>{o.executed_quantity}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div>
                  <h3 className="text-sm font-medium text-zinc-400">Deals</h3>
                  <table className="mt-1 w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-zinc-800 text-zinc-500">
                        <th className="py-1">id</th>
                        <th>figi</th>
                        <th>side</th>
                        <th>qty</th>
                        <th>price</th>
                      </tr>
                    </thead>
                    <tbody>
                      {deals.map((d) => (
                        <tr key={d.deal_id} className="border-b border-zinc-900">
                          <td className="py-1">{d.deal_id}</td>
                          <td>{d.figi}</td>
                          <td>{d.side}</td>
                          <td>{d.quantity}</td>
                          <td>{d.price}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
        </section>

        <section className="mt-6">
          <h2 className="text-lg font-medium">Market Data</h2>
          {lastPrice && (
            <p className="mt-2 text-sm">
              Последняя цена: <span className="font-medium">{lastPrice.price}</span>{" "}
              <span className="text-zinc-500">({lastPrice.ticker})</span>
            </p>
          )}
          <div className="mt-3">
            <CandleChart candles={candles} />
          </div>
          {candles.length > 0 && (
            <table className="mt-3 w-full text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-800 text-xs text-zinc-400">
                  <th className="py-1">timestamp</th>
                  <th>open</th>
                  <th>high</th>
                  <th>low</th>
                  <th>close</th>
                  <th>volume</th>
                </tr>
              </thead>
              <tbody>
                {candles.map((c) => (
                  <tr key={c.timestamp} className="border-b border-zinc-900 text-xs">
                    <td className="py-1">{c.timestamp}</td>
                    <td>{c.open}</td>
                    <td>{c.high}</td>
                    <td>{c.low}</td>
                    <td>{c.close}</td>
                    <td>{c.volume}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </main>
  );
}

export default App;
