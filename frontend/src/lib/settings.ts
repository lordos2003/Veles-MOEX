/** UI operational settings (U5: polling interval), stored in localStorage. */

const KEY = "veles.ui.poll_interval_ms";
const DEFAULT = 5_000;

/** Poll interval for bot/list pages in milliseconds; 0 disables polling. */
export function getPollIntervalMs(): number {
  if (typeof localStorage === "undefined") return DEFAULT;
  const raw = Number(localStorage.getItem(KEY));
  return Number.isFinite(raw) && raw >= 0 ? raw : DEFAULT;
}

export function setPollIntervalMs(ms: number): void {
  localStorage.setItem(KEY, String(ms));
}
