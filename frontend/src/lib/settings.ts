/** UI operational settings (U5: polling interval), stored in localStorage. */

const KEY = "veles.ui.poll_interval_ms";
const DEFAULT = 5_000;

/**
 * Poll interval for bot/list pages in milliseconds; 0 disables polling.
 * A missing/blank/invalid stored value falls back to DEFAULT — a missing key
 * must never read as 0 (review round 3, B8: `Number(null) === 0` used to turn
 * new users into an auto-refresh storm once the detail page wired it up).
 */
export function getPollIntervalMs(): number {
  if (typeof localStorage === "undefined") return DEFAULT;
  const raw = localStorage.getItem(KEY);
  if (raw === null || raw.trim() === "") return DEFAULT;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? n : DEFAULT;
}

export function setPollIntervalMs(ms: number): void {
  localStorage.setItem(KEY, String(ms));
}
