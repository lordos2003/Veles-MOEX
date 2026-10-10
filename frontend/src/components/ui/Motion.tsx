import type { ReactNode } from "react";
import { m, useReducedMotion } from "motion/react";

/**
 * R10: каскадное появление блоков при монтировании страницы (stagger 60 мс,
 * сдвиг 10 px, ≤ 400 мс). Анимируется только монтирование — повторные
 * загрузки данных внутри страницы элементы не перемонтируют. При
 * prefers-reduced-motion смещения нет вообще (в том числе в начальном
 * кадре) — остаётся только плавная прозрачность.
 */
const container = { hidden: {}, show: { transition: { staggerChildren: 0.06 } } };
const moving = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] as const } },
};
const still = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: 0.2 } },
};

export function Stagger(props: { children: ReactNode; className?: string }) {
  return (
    <m.div className={props.className} variants={container} initial="hidden" animate="show">
      {props.children}
    </m.div>
  );
}

export function StaggerItem(props: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <m.div className={props.className} variants={reduce ? still : moving}>
      {props.children}
    </m.div>
  );
}
