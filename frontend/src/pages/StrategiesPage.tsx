import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { StrategyResponse, StrategyVersionResponse } from "../types";
import { Button, ErrorBanner, Loading } from "../components/FormControls";

export function StrategiesListPage() {
  const [strategies, setStrategies] = useState<StrategyResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setError(null);
    try {
      setStrategies(await api.get<StrategyResponse[]>("/api/strategies"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Стратегии</h2>
        <Button onClick={() => navigate("/strategies/new")}>+ Новая стратегия</Button>
      </div>
      <ErrorBanner text={error} />
      {!strategies ? (
        <Loading />
      ) : strategies.length === 0 ? (
        <p className="text-sm text-text-muted">Стратегий пока нет.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {strategies.map((s) => (
            <Link
              key={s.id}
              to={`/strategies/${s.id}`}
              className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 hover:border-zinc-600"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-zinc-100">{s.name}</span>
                <span className="text-xs text-text-muted">версия {s.versions}</span>
              </div>
              {s.description ? <p className="mt-1 text-xs text-text-muted">{s.description}</p> : null}
              <p className="mt-1 text-xs text-text-muted">
                Обновлена: {s.updated_at ? new Date(s.updated_at).toLocaleString("ru-RU") : "—"}
              </p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export function StrategyDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const strategyId = id ? Number(id) : null;
  const [strategy, setStrategy] = useState<StrategyResponse | null>(null);
  const [versions, setVersions] = useState<StrategyVersionResponse[]>([]);
  const [viewVersion, setViewVersion] = useState<StrategyVersionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (strategyId === null) return;
    Promise.all([
      api.get<StrategyResponse>(`/api/strategies/${strategyId}`),
      api.get<StrategyVersionResponse[]>(`/api/strategies/${strategyId}/versions`),
    ])
      .then(([s, v]) => {
        setStrategy(s);
        setVersions(v);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [strategyId]);

  if (error) return <ErrorBanner text={error} />;
  if (!strategy) return <Loading />;

  const shown = viewVersion?.config ?? strategy.config;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">{strategy.name}</h2>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => navigate("/strategies")}>
            Назад
          </Button>
          <Button onClick={() => navigate(`/strategies/${strategy.id}/edit`)}>Изменить</Button>
        </div>
      </div>
      {strategy.description ? <p className="text-sm text-zinc-400">{strategy.description}</p> : null}
      <p className="text-xs text-text-muted">
        Версия {strategy.versions} · создана:{" "}
        {strategy.created_at ? new Date(strategy.created_at).toLocaleString("ru-RU") : "—"} ·
        обновлена: {strategy.updated_at ? new Date(strategy.updated_at).toLocaleString("ru-RU") : "—"}
      </p>

      {viewVersion ? (
        <p className="text-xs text-amber-400">
          Просмотр версии {viewVersion.version} от{" "}
          {new Date(viewVersion.created_at).toLocaleString("ru-RU")} (только чтение)
        </p>
      ) : null}

      <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
        <pre className="max-h-[32rem] overflow-auto text-xs text-zinc-300">
          {JSON.stringify(shown, null, 2)}
        </pre>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium text-zinc-300">История версий</p>
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs text-text-muted">
              <th className="py-1">версия</th>
              <th>создана</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.id} className="border-b border-zinc-900">
                <td className="py-1">{v.version}</td>
                <td>{new Date(v.created_at).toLocaleString("ru-RU")}</td>
                <td>
                  <Button variant="ghost" onClick={() => setViewVersion(v)}>
                    Показать
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
