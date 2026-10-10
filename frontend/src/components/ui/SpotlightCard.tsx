import { useEffect, useRef } from "react";
import type { PointerEvent, ReactNode } from "react";

/**
 * R9: «прожектор» — мягкая подсветка карточки, следящая за курсором.
 * Идея — паттерн «Magic Card» (Magic UI, MIT, magicui.design); реализация
 * написана с нуля: JS лишь записывает --mx/--my, свечение рисует CSS
 * (.spotlight в index.css) радиальным градиентом, без layout и без
 * зависимостей. На touch-устройствах и при prefers-reduced-motion CSS
 * эффект не включает вовсе.
 */
export function SpotlightCard(props: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const frame = useRef(0);

  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== "mouse") return;
    const el = ref.current;
    if (!el) return;
    const { clientX, clientY } = e;
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      const r = el.getBoundingClientRect();
      el.style.setProperty("--mx", `${clientX - r.left}px`);
      el.style.setProperty("--my", `${clientY - r.top}px`);
    });
  };

  return (
    <div
      ref={ref}
      onPointerMove={onPointerMove}
      className={"spotlight rounded-card border border-border-soft bg-surface/70 shadow-card " + (props.className ?? "")}
    >
      {props.children}
    </div>
  );
}
