import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { m, useReducedMotion } from "motion/react";

/**
 * R10: появление страницы при смене маршрута (opacity + 8 px, 250 мс).
 * Ключ — только pathname: автообновление данных внутри страницы не
 * перезапускает анимацию. При prefers-reduced-motion смещения нет вовсе
 * (только прозрачность).
 */
export function PageTransition(props: { children: ReactNode }) {
  const { pathname } = useLocation();
  const reduce = useReducedMotion();
  return (
    <m.div
      key={pathname}
      initial={reduce ? { opacity: 0 } : { opacity: 0, y: 8 }}
      animate={reduce ? { opacity: 1 } : { opacity: 1, y: 0 }}
      transition={{ duration: reduce ? 0.15 : 0.25, ease: [0.16, 1, 0.3, 1] }}
    >
      {props.children}
    </m.div>
  );
}
