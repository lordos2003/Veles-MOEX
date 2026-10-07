import { useCallback, useEffect, useState } from "react";
import { getPollIntervalMs, setPollIntervalMs } from "./settings";

/**
 * Poll interval state shared by the bot list and bot detail pages (U5),
 * persisted in localStorage via settings.ts. A single hook guards against the
 * two pages drifting apart (review round 3, B8): each page reads the same
 * store and the same `pollMs <= 0` rule below.
 */
export function usePollInterval(): [number, (ms: number) => void] {
  const [pollMs, setPollMs] = useState(getPollIntervalMs);
  const change = useCallback((ms: number) => {
    setPollMs(ms);
    setPollIntervalMs(ms);
  }, []);
  return [pollMs, change];
}

/**
 * Run `tick` every `pollMs` ms. No interval is created at all when
 * `pollMs <= 0` — an interval of 0 would fire on every macrotask (B8). `tick`
 * must be referentially stable (useCallback) so the interval is not recreated
 * on each render.
 */
export function usePolling(tick: () => void, pollMs: number): void {
  useEffect(() => {
    if (pollMs <= 0) return;
    const t = window.setInterval(tick, pollMs);
    return () => window.clearInterval(t);
  }, [tick, pollMs]);
}
