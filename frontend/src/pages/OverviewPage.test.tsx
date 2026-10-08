// @vitest-environment jsdom
/**
 * MVP-7.4 UI tests for «Обзор»: U1 (свободно/эквити из портфеля, «—» +
 * пометка, когда портфель недоступен), U2 (живой поиск с выпадающим списком,
 * счётчик «Найдено», состояние «ничего не найдено», клавиатура),
 * U3 (подпись без «(тип / валюта)»), U4 (зелёная плашка успеха после
 * синхронизации).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OverviewPage } from "./OverviewPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const { accounts, instruments } = vi.hoisted(() => ({
  accounts: [
    {
      account_id: "a1",
      id: 1,
      is_saved: true,
      broker: "tinvest",
      currency: "RUB",
      available_cash: "900.25",
      equity: "1250.50",
      portfolio_available: true,
      currencies: [],
      name: "Основной",
      account_type: "TINKOFF",
      status: "ACCOUNT_STATUS_OPEN",
      opened_at: null,
      closed_at: null,
    },
    {
      account_id: "a2",
      id: null,
      is_saved: false,
      broker: "tinvest",
      currency: "RUB",
      available_cash: "0",
      equity: "0",
      portfolio_available: false,
      currencies: [],
      name: "Закрытый",
      account_type: null,
      status: "ACCOUNT_STATUS_CLOSED",
      opened_at: null,
      closed_at: null,
    },
  ],
  instruments: [
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
    },
    {
      id: 2,
      figi: "BBG004730R19",
      ticker: "GAZP",
      name: "Газпром",
      instrument_type: "SHARE",
      currency: "RUB",
      lot_size: 10,
      tick_size: "0.01",
      trading_status: "TRADING_AVAILABLE",
      exchange: "MOEX",
      is_active: true,
    },
    {
      id: 3,
      figi: "BBG012345678",
      ticker: "ABIO",
      name: "Артген",
      instrument_type: "SHARE",
      currency: "RUB",
      lot_size: 1,
      tick_size: "0.01",
      trading_status: "TRADING_AVAILABLE",
      exchange: "MOEX",
      is_active: true,
    },
  ],
}));

vi.mock("../api", () => ({
  api: {
    get: vi.fn(async (path: string) => {
      if (path === "/api/health") return { status: "ok" };
      if (path === "/api/tinvest/status") return { status: "connected", message: "ok" };
      if (path === "/api/accounts") return accounts;
      if (path === "/api/instruments?active=true") return instruments;
      if (path === "/api/positions") return [];
      if (path === "/api/orders") return [];
      if (path === "/api/deals") return [];
      throw new Error(`unexpected path: ${path}`);
    }),
    post: vi.fn(async () => ({ synced: 3 })),
  },
}));

vi.mock("../components/CandleChart", () => ({
  default: () => <div data-testid="chart" />,
}));

const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response);

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.mocked(fetchMock).mockClear();
});

describe("MVP-7.4: «Обзор» (U1/U2/U3/U4)", () => {
  it("U1: показывает свободно/эквити из портфеля; у закрытого счёта «—» и пометка", async () => {
    render(<OverviewPage />);
    await screen.findByText("Основной");

    expect(screen.getByText(/свободно: 900\.25 · эквити: 1250\.50/)).toBeTruthy();
    expect(screen.getByText(/свободно: — · эквити: —/)).toBeTruthy();
    expect(screen.getByText("портфель недоступен")).toBeTruthy();
  });

  it("U2: ввод фильтрует по вхождению, показывает «Найдено: N из M» и «Ничего не найдено»", async () => {
    render(<OverviewPage />);
    const input = await screen.findByRole("combobox");

    fireEvent.focus(input);
    expect(screen.getByText("Найдено: 3 из 3")).toBeTruthy();

    fireEvent.change(input, { target: { value: "артг" } });
    expect(screen.getByText("Найдено: 1 из 3")).toBeTruthy();
    expect(screen.getByText("ABIO — Артген")).toBeTruthy();
    expect(screen.queryByText("SBER — Сбербанк")).toBeNull();

    fireEvent.change(input, { target: { value: "zzz" } });
    expect(screen.getByText("Найдено: 0 из 3")).toBeTruthy();
    expect(screen.getByText("Ничего не найдено")).toBeTruthy();
  });

  it("U3: подпись инструмента без «(тип / валюта)»", async () => {
    render(<OverviewPage />);
    const input = await screen.findByRole("combobox");
    fireEvent.focus(input);
    expect(screen.queryByText(/\(SHARE \/ RUB\)/)).toBeNull();
    expect(screen.getByText("SBER — Сбербанк")).toBeTruthy();
  });

  it("U2: выбор стрелками и Enter — выбранный инструмент подставляется и грузит рынок", async () => {
    render(<OverviewPage />);
    const input = (await screen.findByRole("combobox")) as HTMLInputElement;

    fireEvent.change(input, { target: { value: "газ" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(input.value).toBe("GAZP — Газпром");
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/market-data/BBG004730R19/last-price"),
      ),
    );
  });

  it("U2: Escape закрывает выпадающий список", async () => {
    render(<OverviewPage />);
    const input = (await screen.findByRole("combobox")) as HTMLInputElement;

    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByText(/Найдено:/)).toBeNull();
  });

  it("M1/M2: поле показывает подпись выбранной бумаги, фокус открывает полный список", async () => {
    render(<OverviewPage />);
    const input = (await screen.findByRole("combobox")) as HTMLInputElement;

    // M2: on first load the selected paper (first instrument, chart shown)
    // must be visible in the field, not an empty input.
    expect(input.value).toBe("SBER — Сбербанк");

    // M1: refocus does not leave the long label as the query — the full list
    // is shown instead of «Ничего не найдено».
    fireEvent.focus(input);
    expect(screen.getByText("Найдено: 3 из 3")).toBeTruthy();
  });

  it("U4: после синхронизации показывается плашка успеха (не ошибка)", async () => {
    render(<OverviewPage />);
    const button = await screen.findByRole("button", { name: /Синхронизировать инструменты/ });
    fireEvent.click(button);

    await screen.findByText("Синхронизировано инструментов: 3");
    expect(screen.queryByText(/Синхронизировано инструментов: 3/)?.closest("div")?.className).toContain(
      "emerald",
    );
  });
});
