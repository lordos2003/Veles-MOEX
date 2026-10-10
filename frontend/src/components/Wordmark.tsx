/** Оригинальный знак и вордмарк Veles-MOEX (векторный, без внешних ресурсов).
    Цвета — токены --color-logo-* (инвариантны между темами, T5). */
export function Logo(props: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" className={props.className ?? "h-8 w-8"}>
      <defs>
        <linearGradient id="vm-logo-g" x1="8" y1="4" x2="56" y2="60" gradientUnits="userSpaceOnUse">
          <stop offset="0" style={{ stopColor: "var(--color-logo-1)" }} />
          <stop offset="1" style={{ stopColor: "var(--color-logo-2)" }} />
        </linearGradient>
      </defs>
      <rect x="3" y="3" width="58" height="58" rx="14" fill="url(#vm-logo-g)" />
      <path d="M17 20 32 46 47 20" fill="none" stroke="var(--color-logo-stroke)" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M47 11v9" stroke="var(--color-logo-spark)" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="inline-flex items-center gap-2.5">
      <Logo />
      <span className="whitespace-nowrap text-xl font-semibold tracking-tight text-text">
        Veles<span className="text-accent-bright">-MOEX</span>
      </span>
    </span>
  );
}
