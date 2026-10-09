// @vitest-environment jsdom
/**
 * REV3 B8 (page-level test): BotDetailPage must not create a polling interval
 * when the poll interval is <= 0, and with the default (5000 ms) it must poll
 * exactly once per period. Before the fix the page wired `setInterval(..., 0)`
 * when localStorage was empty (getPollIntervalMs read Number(null) === 0) —
 * ~230 requests/s against /api/bots/1.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api";
import type { BotResponse } from "../types";
import { BotDetailPage, BotsPage } from "./BotsPage";

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

async function openCreate() {
  render(
    <MemoryRouter initialEntries={["/bots"]}>
      <Routes>
        <Route path="/bots" element={<BotsPage />} />
      </Routes>
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "+ Создать бота" }));
  await screen.findByPlaceholderText("Поиск по тикеру, названию или FIGI…");
}

describe("MVP-7.7 P1/P2: форма создания бота — единый поиск «Ценная бумага»", () => {
  /**
   * The instrument list contains a paper with `id: null` (NOLOCAL) — such a
   * paper must not be offered in the picker (P2), like on «Боты» before.
   */
  function mockCreatePage() {
    getMock.mockImplementation(async (path: string) => {
      if (path === "/api/bots") return [];
      if (path === "/api/strategies") return [{ id: 1, name: "Стратегия 1", version: 1, active: true }];
      if (path === "/api/strategies/1/versions") {
        return [{ id: 1, version: 1, created_at: "2026-01-01T00:00:00Z" }];
      }
      if (path === "/api/accounts") {
        return [
          {
            id: 1,
            account_id: "acc-1",
            name: "Основной",
            currencies: ["RUB"],
            available_cash: "0",
            equity: "0",
            is_saved: true,
            broker: "tinvest",
            currency: "RUB",
            account_type: null,
            status: null,
            opened_at: null,
            closed_at: null,
          },
        ];
      }
      if (path === "/api/instruments?active=true") {
        return [
          {
            id: 1,
            figi: "BBG004730N88",
            ticker: "SBER",
            name: "Сбербанк",
            instrument_type: "SHARE",
            currency: "RUB",
            lot_size: 10,
            tick_size: "0.01",
            trading_status: "TRADING_AVAILABLE",
            exchange: "MOEX",
            is_active: true,
            first_1min_candle_date: null,
            first_1day_candle_date: null,
          },
          {
            id: null,
            figi: "BBG0000000000",
            ticker: "NOLOCAL",
            name: "Без локального id",
            instrument_type: "SHARE",
            currency: "RUB",
            lot_size: 1,
            tick_size: "0.01",
            trading_status: "TRADING_AVAILABLE",
            exchange: "MOEX",
            is_active: true,
            first_1min_candle_date: null,
            first_1day_candle_date: null,
          },
        ];
      }
      throw new Error(`unexpected path: ${path}`);
    });
  }

  /** The label and the control are siblings inside one field div. */
  function fieldControl(selector: string, label: RegExp): HTMLInputElement | HTMLSelectElement {
    // getByText is ambiguous here (option labels contain the same words).
    const el = screen.getAllByText(label).find((e) => e.tagName === "LABEL");
    if (!el) throw new Error(`field label not found for ${label}`);
    const cell = el.parentElement;
    if (!cell) throw new Error(`field cell not found for ${label}`);
    const control = cell.querySelector<HTMLInputElement | HTMLSelectElement>(selector);
    if (!control) throw new Error(`control ${selector} not found for ${label}`);
    return control;
  }

  function fillTextFields() {
    const name = fieldControl("input", /Название/) as HTMLInputElement;
    fireEvent.change(name, { target: { value: "Бот-тест" } });
  }

  async function fillSelects() {
    fireEvent.change(fieldControl("select", /Стратегия/), { target: { value: "1" } });
    await waitFor(() =>
      expect((fieldControl("select", /Версия/) as HTMLSelectElement).options.length).toBeGreaterThan(1),
    );
    fireEvent.change(fieldControl("select", /Версия/), { target: { value: "1" } });
    fireEvent.change(fieldControl("select", /Счёт/), { target: { value: "1" } });
  }

  beforeEach(() => {
    // The shared hooks above ran first (fake timers); disable the poll for the
    // list page and install the create-flow mock.
    vi.useRealTimers();
    localStorage.setItem("veles.ui.poll_interval_ms", "0");
    mockCreatePage();
  });

  it("поиск по тикеру выбирает бумагу; в POST /api/bots уходит instrument_id", async () => {
    const postMock = vi.mocked(api.post);
    postMock.mockResolvedValue({} as BotResponse);
    await openCreate();
    fillTextFields();
    await fillSelects();

    const picker = screen.getByPlaceholderText("Поиск по тикеру, названию или FIGI…") as HTMLInputElement;
    fireEvent.change(picker, { target: { value: "сбер" } });
    fireEvent.keyDown(picker, { key: "ArrowDown" });
    fireEvent.keyDown(picker, { key: "Enter" });
    expect(picker.value).toBe("SBER — Сбербанк");

    fireEvent.click(screen.getByRole("button", { name: "Создать (в состоянии «Остановлен»)" }));
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    expect(postMock).toHaveBeenCalledWith("/api/bots", expect.objectContaining({ instrument_id: 1 }));
  });

  it("без выбора бумаги кнопка «Создать» неактивна", async () => {
    await openCreate();
    fillTextFields();
    await fillSelects();

    const create = () =>
      screen.getByRole("button", { name: "Создать (в состоянии «Остановлен»)" }) as HTMLButtonElement;
    expect(create().disabled).toBe(true);

    const picker = screen.getByPlaceholderText("Поиск по тикеру, названию или FIGI…") as HTMLInputElement;
    fireEvent.change(picker, { target: { value: "сбер" } });
    fireEvent.keyDown(picker, { key: "ArrowDown" });
    fireEvent.keyDown(picker, { key: "Enter" });
    expect(create().disabled).toBe(false);
  });

  it("бумага без локального id не показывается в списке выбора", async () => {
    await openCreate();
    const picker = screen.getByPlaceholderText("Поиск по тикеру, названию или FIGI…") as HTMLInputElement;

    fireEvent.focus(picker);
    expect(screen.getByText("Найдено: 1 из 1")).toBeTruthy();
    expect(screen.getByText("SBER — Сбербанк")).toBeTruthy();
    expect(screen.queryByText("NOLOCAL — Без локального id")).toBeNull();
  });
});

describe("G5 (MVP-8.0): независимая загрузка данных на «Боты → создать»", () => {
  beforeEach(() => {
    vi.useRealTimers();
    localStorage.setItem("veles.ui.poll_interval_ms", "0");
  });

  it("сбой /api/accounts не мешает бумагам и стратегиям; у «Счёта» своя ошибка", async () => {
    getMock.mockImplementation(async (path: string) => {
      if (path === "/api/bots") return [];
      if (path === "/api/strategies") {
        return [{ id: 1, name: "Стратегия 1", version: 1, active: true }];
      }
      if (path === "/api/accounts") throw new Error("Брокер недоступен: нет токена");
      if (path === "/api/instruments?active=true") {
        return [
          {
            id: 1,
            figi: "BBG004730N88",
            ticker: "SBER",
            name: "Сбербанк",
            instrument_type: "SHARE",
            currency: "RUB",
            lot_size: 10,
            tick_size: "0.01",
            trading_status: "TRADING_AVAILABLE",
            exchange: "MOEX",
            is_active: true,
            first_1min_candle_date: null,
            first_1day_candle_date: null,
          },
        ];
      }
      throw new Error(`unexpected path: ${path}`);
    });

    await openCreate();

    // Бумаги загрузились, несмотря на ошибку счетов.
    const picker = screen.getByPlaceholderText("Поиск по тикеру, названию или FIGI…") as HTMLInputElement;
    fireEvent.focus(picker);
    expect(screen.getByText("Найдено: 1 из 1")).toBeTruthy();
    expect(screen.getByText("SBER — Сбербанк")).toBeTruthy();

    // Стратегии тоже доступны.
    expect(screen.getByText("Стратегия 1")).toBeTruthy();

    // Ошибка счетов показана дословно и только у поля «Счёт».
    expect(screen.getByText("Брокер недоступен: нет токена")).toBeTruthy();
  });
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
