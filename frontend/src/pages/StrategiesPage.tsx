import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { StrategyResponse, StrategyVersionResponse } from "../types";
import { Button, ErrorBanner, Loading, TableWrap } from "../components/FormControls";
import { PageHeader } from "../components/PageHeader";
import { SpotlightCard } from "../components/ui/SpotlightCard";

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
      <PageHeader
        title="Стратегии"
        description="Конфигурации входа и усреднения; каждое изменение сохраняется отдельной версией."
        actions={<Button onClick={() => navigate("/strategies/new")}>+ Новая стратегия</Button>}
      />
      <ErrorBanner text={error} />
      {!strategies ? (
        <Loading />
      ) : strategies.length === 0 ? (
        <p className="text-sm text-text-muted">Стратегий пока нет.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {strategies.map((s) => (
            <SpotlightCard key={s.id}>
              <Link to={`/strategies/${s.id}`} className="block rounded-card p-4 sm:p-5">
                <div className="flex items-start justify-between gap-3">
                  <span className="min-w-0 break-words text-base font-medium text-text">{s.name}</span>
                  <span className="shrink-0 rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-text-secondary">
                    версия {s.versions}
                  </span>
                </div>
                {s.description ? <p className="mt-2 text-sm text-text-muted">{s.description}</p> : null}
                <p className="mt-3 text-xs text-text-muted">
                  Обновлена: {s.updated_at ? new Date(s.updated_at).toLocaleString("ru-RU") : "—"}
                </p>
              </Link>
            </SpotlightCard>
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
      <PageHeader
        title={strategy.name}
        actions={
          <>
            <Button variant="ghost" onClick={() => navigate("/strategies")}>
              Назад
            </Button>
            <Button onClick={() => navigate(`/strategies/${strategy.id}/edit`)}>Изменить</Button>
          </>
        }
      />
      {strategy.description ? <p className="text-sm text-text-muted">{strategy.description}</p> : null}
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

      <div className="rounded-card border border-zinc-800 bg-zinc-950/70 p-4">
        <pre className="num max-h-[32rem] overflow-auto text-xs leading-relaxed text-zinc-300" tabIndex={0} aria-label="Конфигурация стратегии (JSON)">
          {JSON.stringify(shown, null, 2)}
        </pre>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium text-text-secondary">История версий</p>
        <TableWrap>
        <table className="data-table">
          <thead>
            <tr>
              <th>версия</th>
              <th>создана</th>
              <th>
                <span className="sr-only">действия</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.id}>
                <td>{v.version}</td>
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
        </TableWrap>
      </div>
    </div>
  );
}
