// @vitest-environment jsdom
/**
 * REV3 B8 (page-level test): BotDetailPage must not create a polling interval
 * when the poll interval is <= 0, and with the default (5000 ms) it must poll
 * exactly once per period. Before the fix the page wired `setInterval(..., 0)`
 * when localStorage was empty (getPollIntervalMs read Number(null) === 0) —
 * ~230 requests/s against /api/bots/1.
 */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api";
import type { BotResponse } from "../types";
import { BotDetailPage } from "./BotsPage";

vi.mock("../api", () => ({
  ApiError: class ApiError extends Error {},
  fieldErrors: () => ({}),
  verbatimMessage: (detail: unknown) => String(detail),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const getMock = api.get as unknown as Mock;

const bot: BotResponse = {
  id: 1,
  name: "Тестовый бот",
  status: "STOPPED",
  strategy_version_id: 1,
  account_id: 2,
  instrument_id: 3,
  deposit: "100000",
  started_at: null,
  stopped_at: null,
  stop_reason: null,
  deal_error: null,
  last_error: null,
  last_skip_reason: null,
};

function mockPage(): void {
  getMock.mockImplementation(async (path: string) => {
    if (path === "/api/bots/1") return bot;
    if (path === "/api/bots/1/deal") return null;
    if (path === "/api/bots/1/deals?limit=50") return [];
    if (path === "/api/strategies") return [];
    if (path === "/api/instruments?active=true") return [];
    if (path === "/api/accounts") return [];
    throw new Error(`unexpected path ${path}`);
  });
}

function botCalls(): number {
  return getMock.mock.calls.filter(([p]) => p === "/api/bots/1").length;
}

/** Flush the promise chain of `load()` (api mocks + Promise.all + setState). */
async function settle(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

function renderDetail(): void {
  render(
    <MemoryRouter initialEntries={["/bots/1"]}>
      <Routes>
        <Route path="/bots/:id" element={<BotDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
  getMock.mockClear();
  mockPage();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("REV3 B8: опрос страницы бота", () => {
  it("пустой localStorage → default 5000: один запрос за период", async () => {
    renderDetail();
    await settle();
    expect(botCalls()).toBe(1);
    expect(screen.getByRole("heading", { name: "Тестовый бот" })).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(4999);
    });
    expect(botCalls()).toBe(1);

    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    await settle();
    expect(botCalls()).toBe(2);
  });

  it("явный 0 («выкл») → повторных запросов нет", async () => {
    localStorage.setItem("veles.ui.poll_interval_ms", "0");
    renderDetail();
    await settle();
    expect(botCalls()).toBe(1);

    await act(async () => {
      vi.advanceTimersByTime(20000);
    });
    await settle();
    expect(botCalls()).toBe(1);
  });
});
