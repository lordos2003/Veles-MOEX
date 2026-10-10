import { useSyncExternalStore } from "react";

/** MVP-8.3, раунд 2 (T2/T4): хранилище темы. Ключ совпадает с theme-init.js —
 *  скрипт в <head> применяет тему до отрисовки, а этот модуль её поддерживает. */
export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "veles-theme";
export const DEFAULT_THEME: Theme = "dark";

const THEME_COLOR: Record<Theme, string> = {
  dark: "#0c0e16",
  light: "#f6f7fc",
};

function isTheme(value: string | null | undefined): value is Theme {
  return value === "dark" || value === "light";
}

function readStored(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(value) ? value : null;
  } catch {
    // Приватный режим/запрет хранилища: остаёмся на теме по умолчанию.
    return null;
  }
}

function resolve(): Theme {
  return readStored() ?? DEFAULT_THEME;
}

let current: Theme = typeof window === "undefined" ? DEFAULT_THEME : resolve();
const listeners = new Set<() => void>();

/** Применяет тему к DOM: data-theme (переключает CSS-токены), color-scheme и
 *  meta theme-color для адресной строки браузера. */
function applyDom(theme: Theme) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (meta) meta.content = THEME_COLOR[theme];
  const scheme = document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]');
  if (scheme) scheme.content = theme;
}

function emit() {
  for (const listener of listeners) listener();
}

export function getTheme(): Theme {
  return current;
}

export function setTheme(theme: Theme) {
  if (!isTheme(theme) || theme === current) return;
  current = theme;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Хранилище недоступно: тема живёт только в DOM до перезагрузки.
  }
  applyDom(theme);
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// Синхронизация между вкладками (T4): смена темы в одной вкладке применяется
// в остальных; удаление ключа возвращает тему по умолчанию.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key !== THEME_STORAGE_KEY) return;
    const next = isTheme(event.newValue) ? event.newValue : DEFAULT_THEME;
    if (next === current) return;
    current = next;
    applyDom(next);
    emit();
  });
  applyDom(current);
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getTheme, () => DEFAULT_THEME);
}
