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
            ? "bg-error-soft/70 text-error ring-error-border/60"
            : live
              ? "bg-warning-soft/70 text-warning ring-warning-border/60"
              : "bg-success-soft/70 text-success ring-success-border/60")
        }
      >
        <span
          aria-hidden="true"
          className={"h-1.5 w-1.5 rounded-full " + (realMoney ? "bg-error" : live ? "bg-warning" : "bg-success")}
        />
        {live ? "Боевой счёт" : "Песочница"}
      </span>
      {realMoney ? (
        <span className="rounded-full bg-error-soft px-2.5 py-0.5 text-xs font-semibold text-error ring-1 ring-error-border">
          Реальные деньги
        </span>
      ) : null}
      {error ? <span className="text-xs text-error" title={error}>режим недоступен: {error}</span> : null}
    </div>
  );
}
