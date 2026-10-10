import type { ReactNode } from "react";
import { SpotlightCard } from "./ui/SpotlightCard";
import { Skeleton } from "./ui/Skeleton";

/** Плитка показателя на «Обзоре»: подпись, значение, пояснение; skeleton при загрузке. */
export function StatCard(props: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  loading?: boolean;
  tone?: "default" | "success" | "warning" | "error";
}) {
  const toneDot =
    props.tone === "success" ? "bg-success" : props.tone === "warning" ? "bg-warning" : props.tone === "error" ? "bg-error" : null;
  return (
    <SpotlightCard className="h-full p-4">
      <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
        {toneDot && !props.loading ? <span aria-hidden="true" className={"h-1.5 w-1.5 rounded-full " + toneDot} /> : null}
        {props.label}
      </p>
      {props.loading ? (
        <>
          <Skeleton className="mt-3 h-8 w-24" />
          <Skeleton className="mt-2 h-3 w-32" />
        </>
      ) : (
        <>
          <p className={(typeof props.value === "number" ? "num " : "") + "mt-2 text-3xl font-semibold tracking-tight text-text"}>{props.value}</p>
          {props.hint ? <p className="mt-1 text-xs text-text-muted">{props.hint}</p> : null}
        </>
      )}
    </SpotlightCard>
  );
}
