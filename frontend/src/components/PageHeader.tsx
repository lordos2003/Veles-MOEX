import type { ReactNode } from "react";

/** Заголовок страницы: единая иерархия h2 + пояснение + действия справа. */
export function PageHeader(props: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h2 className="text-2xl font-semibold tracking-tight text-text sm:text-3xl">{props.title}</h2>
        {props.description ? <div className="mt-1.5 max-w-2xl text-sm text-text-muted">{props.description}</div> : null}
      </div>
      {props.actions ? <div className="flex flex-wrap items-center gap-2">{props.actions}</div> : null}
    </div>
  );
}
