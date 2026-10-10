/** Заглушка загрузки: прозрачность пульсирует (отключается при reduced-motion). */
export function Skeleton(props: { className?: string }) {
  return <div aria-hidden="true" className={"skeleton " + (props.className ?? "h-4 w-full")} />;
}

/** Заглушка страницы для React.lazy/Suspense. */
export function PageSkeleton() {
  return (
    <div role="status" aria-live="polite" aria-label="Загрузка страницы" className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-36 w-full rounded-card" />
      <Skeleton className="h-56 w-full rounded-card" />
      <span className="sr-only">Загрузка…</span>
    </div>
  );
}
