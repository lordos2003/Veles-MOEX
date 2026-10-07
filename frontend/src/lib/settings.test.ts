// @vitest-environment jsdom
/**
 * REV3 B8: getPollIntervalMs must not turn a missing/blank/invalid key into 0.
 * `Number(null) === 0` used to pass the `>= 0` check, so a fresh browser got
 * "polling off" instead of the 5000 ms default (and the detail page then wired
 * an interval of 0 — review round 3: ~230 requests/s on /bots/1).
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { getPollIntervalMs, setPollIntervalMs } from "./settings";

const KEY = "veles.ui.poll_interval_ms";

describe("REV3 B8: getPollIntervalMs", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it("отсутствующий ключ → DEFAULT (5000)", () => {
    expect(getPollIntervalMs()).toBe(5000);
  });

  it("пустое и «мусорное» значение → DEFAULT", () => {
    localStorage.setItem(KEY, "");
    expect(getPollIntervalMs()).toBe(5000);
    localStorage.setItem(KEY, "abc");
    expect(getPollIntervalMs()).toBe(5000);
    localStorage.setItem(KEY, "Infinity");
    expect(getPollIntervalMs()).toBe(5000);
  });

  it("отрицательное значение → DEFAULT", () => {
    localStorage.setItem(KEY, "-5");
    expect(getPollIntervalMs()).toBe(5000);
  });

  it("явный 0 → выключено (0), остаётся валидным", () => {
    localStorage.setItem(KEY, "0");
    expect(getPollIntervalMs()).toBe(0);
  });

  it("валидные значения проходят; set/get — round-trip", () => {
    setPollIntervalMs(10000);
    expect(getPollIntervalMs()).toBe(10000);
    localStorage.setItem(KEY, " 5000 ");
    expect(getPollIntervalMs()).toBe(5000);
  });
});
