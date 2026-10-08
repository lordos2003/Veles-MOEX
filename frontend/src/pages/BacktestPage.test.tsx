// @vitest-environment jsdom
/**
 * U11 (MVP-7.5): the backtest form sends the picked period as ISO timestamps,
 * and an empty period reports «Укажите период.» without a request.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BacktestPage } from "./BacktestPage";
import type { BacktestResponse } from "../types";

vi.mock("../api", () => ({
  ApiError: class ApiError extends Error {},
  fieldErrors: () => ({}),
  verbatimMessage: (d: unknown) => String(d),
  api: {
    get: vi.fn(async (path: string) => {
      if (path === "/api/strategies") return [{ id: 1, name: "Стратегия 1", version: 1, active: true }];
      if (path === "/api/instruments?active=true") {
        return [{ id: 1, ticker: "SBER", figi: "BBG004730N88", name: "Сбербанк", active: true }];
      }
      if (path === "/api/strategies/1/versions") {
        return [{ id: 1, version: 1, config: { timeframe: "1h" } }];
      }
      throw new Error(`unexpected path: ${path}`);
    }),
    post: vi.fn(async () => ({
      initial_capital: "100000",
      final_capital: "101000",
      gross_pnl: "1000",
      net_pnl: "970",
      roi: "0.97%",
      total_fees: "30",
      num_trades: 1,
      winning_trades: 1,
      losing_trades: 0,
      win_rate: "100%",
      average_trade: "970",
      average_duration: "1h",
      max_drawdown: "0%",
      deals: [],
      orders: [],
      executions: [],
    } as BacktestResponse)),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

afterEach(() => cleanup());

function selectByLabel(label: string, value: string) {
  const cell = screen.getByText(label).parentElement;
  if (!cell) throw new Error(`field cell not found for ${label}`);
  const sel = cell.querySelector("select");
  if (!sel) throw new Error(`select not found for ${label}`);
  fireEvent.change(sel, { target: { value } });
}

function fillRequiredFields() {
  fireEvent.click(screen.getByRole("radio", { name: "Инлайн-конфигурация" }));
  const json = screen.getByPlaceholderText('{"name": "", "direction": "LONG", "entry": {...}, "exit": {...}}');
  fireEvent.change(json, { target: { value: '{"timeframe": "1h"}' } });
  selectByLabel("Инструмент", "1");
  fireEvent.change(screen.getByPlaceholderText("например, 100000"), { target: { value: "100000" } });
  for (const fee of screen.getAllByPlaceholderText("например, 0.0003")) {
    fireEvent.change(fee, { target: { value: "0.0003" } });
  }
  fireEvent.change(screen.getByPlaceholderText("например, 0.001"), { target: { value: "0.001" } });
}

describe("BacktestPage: U11 период", () => {
  it("пустой период: ошибка у поля, запрос не уходит", async () => {
    const { api } = await import("../api");
    render(<BacktestPage />);
    await screen.findByText("SBER · Сбербанк");
    fillRequiredFields();

    fireEvent.click(screen.getByRole("button", { name: "Запустить бэктест" }));
    expect(screen.getByText("Укажите период.")).toBeTruthy();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("выбранный период уходит в запросе ISO-строками", async () => {
    const { api } = await import("../api");
    render(<BacktestPage />);
    await screen.findByText("SBER · Сбербанк");
    fillRequiredFields();

    // Дата без фейковых таймеров: берём дни прошлого месяца (заведомо в прошлом).
    const now = new Date();
    const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const fromExpected = new Date(prev.getFullYear(), prev.getMonth(), 5);
    const toExpected = new Date(prev.getFullYear(), prev.getMonth(), 7);

    fireEvent.click(screen.getByLabelText("Открыть календарь"));
    fireEvent.click(screen.getByLabelText("Предыдущий месяц"));
    fireEvent.click(screen.getByRole("button", { name: `5.${prev.getMonth() + 1}.${prev.getFullYear()}` }));
    fireEvent.click(screen.getByRole("button", { name: `7.${prev.getMonth() + 1}.${prev.getFullYear()}` }));

    fireEvent.click(screen.getByRole("button", { name: "Запустить бэктест" }));
    const post = api.post as unknown as ReturnType<typeof vi.fn>;
    expect(post).toHaveBeenCalledTimes(1);
    const [path, payload] = post.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/api/backtests");
    expect(payload.from).toBe(fromExpected.toISOString());
    expect(payload.to).toBe(toExpected.toISOString());
  });
});
