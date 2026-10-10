import { useRuntime } from "../lib/useRuntime";

/** U2: visible trading mode on every page + red "real money" banner. */
export function ModeBadge() {
  const { runtime, mode, error } = useRuntime();

  if (mode === "checking") {
    return <span className="text-sm text-text-muted">Режим: проверка…</span>;
  }
  const live = mode === "live";
  const realMoney = live && runtime?.live_trading_enabled === true;
  return (
    <div className="flex flex-col items-end gap-1">
      <span
        className={
          "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset " +
          (realMoney
            ? "bg-red-900/60 text-red-200 ring-red-500/40"
            : live
              ? "bg-amber-900/50 text-amber-200 ring-amber-500/30"
              : "bg-emerald-900/40 text-emerald-200 ring-emerald-500/30")
        }
      >
        <span
          aria-hidden="true"
          className={"h-1.5 w-1.5 rounded-full " + (realMoney ? "bg-red-300" : live ? "bg-amber-300" : "bg-emerald-300")}
        />
        {live ? "Боевой счёт" : "Песочница"}
      </span>
      {realMoney ? (
        <span className="rounded-full bg-red-950 px-2.5 py-0.5 text-xs font-semibold text-red-300 ring-1 ring-red-700">
          Реальные деньги
        </span>
      ) : null}
      {error ? <span className="text-xs text-red-400" title={error}>режим недоступен: {error}</span> : null}
    </div>
  );
}
