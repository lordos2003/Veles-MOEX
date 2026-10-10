import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { m } from "motion/react";

/**
 * R10: появление страницы при смене маршрута (opacity + 8 px, 250 мс).
 * Ключ — только pathname: автообновление данных внутри страницы не
 * перезапускает анимацию. При prefers-reduced-motion MotionConfig убирает
 * смещение (остаётся только прозрачность).
 */
export function PageTransition(props: { children: ReactNode }) {
  const { pathname } = useLocation();
  return (
    <m.div
      key={pathname}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
    >
      {props.children}
    </m.div>
  );
}
