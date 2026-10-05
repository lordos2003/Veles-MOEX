import { useRuntime } from "../lib/useRuntime";

/** U2: visible trading mode on every page + red "real money" banner. */
export function ModeBadge() {
  const { runtime, mode, error } = useRuntime();

  if (mode === "checking") {
    return <span className="text-sm text-zinc-500">Режим: проверка…</span>;
  }
  const live = mode === "live";
  const realMoney = live && runtime?.live_trading_enabled === true;
  return (
    <div className="flex flex-col items-end gap-1">
      <span
        className={
          "rounded px-2 py-0.5 text-xs font-medium " +
          (realMoney
            ? "bg-red-900/60 text-red-200"
            : live
              ? "bg-amber-900/50 text-amber-200"
              : "bg-emerald-900/50 text-emerald-200")
        }
      >
        {live ? "Боевой счёт" : "Песочница"}
      </span>
      {realMoney ? (
        <span className="rounded bg-red-950 px-2 py-0.5 text-xs font-semibold text-red-300 ring-1 ring-red-700">
          Реальные деньги
        </span>
      ) : null}
      {error ? <span className="text-xs text-red-400" title={error}>режим недоступен: {error}</span> : null}
    </div>
  );
}
