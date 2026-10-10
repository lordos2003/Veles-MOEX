import { useRef } from "react";
import { setTheme, useTheme, type Theme } from "../lib/theme";

const OPTIONS: readonly { value: Theme; label: string }[] = [
  { value: "dark", label: "Тёмная" },
  { value: "light", label: "Светлая" },
];

/**
 * T2/T3: сегментированный переключатель темы.
 * Семантика — Radio Group (APG): два взаимоисключающих выбора, роуминг
 * tabindex по выбранной опции, стрелки/Home/End перемещают выбор.
 * В шапке — на широких экранах (hidden lg:inline-flex), в мобильном меню —
 * size="lg" (мишень 44px).
 */
export function ThemeSwitcher({ size = "md", className = "" }: { size?: "md" | "lg"; className?: string }) {
  const theme = useTheme();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const select = (index: number) => {
    const wrapped = (index + OPTIONS.length) % OPTIONS.length;
    setTheme(OPTIONS[wrapped].value);
    refs.current[wrapped]?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const index = OPTIONS.findIndex((o) => o.value === theme);
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        select(index + 1);
        event.preventDefault();
        break;
      case "ArrowLeft":
      case "ArrowUp":
        select(index - 1);
        event.preventDefault();
        break;
      case "Home":
        select(0);
        event.preventDefault();
        break;
      case "End":
        select(OPTIONS.length - 1);
        event.preventDefault();
        break;
    }
  };

  const itemClass =
    size === "lg"
      ? "min-h-11 px-4 text-base"
      : "min-h-8 px-3 text-sm";

  return (
    <div
      role="radiogroup"
      aria-label="Тема оформления"
      onKeyDown={onKeyDown}
      className={
        "inline-flex items-center gap-0.5 rounded-control border border-border-soft bg-page/60 p-0.5 " + className
      }
    >
      {OPTIONS.map((option, i) => {
        const selected = theme === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            ref={(el) => {
              refs.current[i] = el;
            }}
            onClick={() => setTheme(option.value)}
            className={
              itemClass +
              " rounded-control font-medium transition-colors duration-(--duration-fast) " +
              (selected
                ? "bg-surface-raised text-text"
                : "text-text-muted hover:bg-surface-raised hover:text-text")
            }
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
