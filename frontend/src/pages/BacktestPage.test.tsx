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
        return [
          {
            id: 1,
            ticker: "SBER",
            figi: "BBG004730N88",
            name: "Сбербанк",
            active: true,
            first_1min_candle_date: "2020-02-07T12:00:00Z",
            first_1day_candle_date: "1998-01-01T12:00:00Z",
          },
          {
            id: 2,
            ticker: "GAZP",
            figi: "BBG004730R89",
            name: "Газпром",
            active: true,
            first_1min_candle_date: null,
            first_1day_candle_date: null,
          },
        ];
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

describe("BacktestPage: MVP-7.6 U12 «портфель данных»", () => {
  const pad2 = (n: number) => String(n).padStart(2, "0");

  /** Local date as DD.MM.YYYY (same conversion the page uses). */
  function dayLabel(iso: string): string {
    const d = new Date(iso);
    return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.${d.getFullYear()}`;
  }

  /**
   * The Field wrapper renders the hint inside the label as a single span with
   * a "ⓘ " prefix, so match the span by contained text (exact string matchers
   * would fail on the prefix).
   */
  function hintContains(text: string) {
    return (content: string, el: Element | null) =>
      el !== null && el.tagName === "SPAN" && content.includes(text);
  }

  function toInline(json: string) {
    fireEvent.click(screen.getByRole("radio", { name: "Инлайн-конфигурация" }));
    const textarea = screen.getByPlaceholderText(
      '{"name": "", "direction": "LONG", "entry": {...}, "exit": {...}}',
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: json } });
  }

  it("H4: 1h берёт дату первой минутной свечи; «Весь период» от earliest", async () => {
    render(<BacktestPage />);
    await screen.findByText("SBER · Сбербанк");

    toInline('{"timeframe": "1h"}');
    selectByLabel("Инструмент", "1");

    // Подсказка под полем и в календаре зависит от (бумага, таймфрейм).
    await screen.findByText(hintContains(`Данные для бэктеста доступны с: ${dayLabel("2020-02-07T12:00:00Z")}`));

    // «Весь период» включён; выбор пресета ставит from = earliest.
    fireEvent.click(screen.getByLabelText("Открыть календарь"));
    fireEvent.click(screen.getByText("Быстрый выбор ▾"));
    const all = screen.getByRole("button", { name: /Весь период/ }) as HTMLButtonElement;
    expect(all.disabled).toBe(false);
    fireEvent.click(all);
    const summary = screen.getByLabelText("Период") as HTMLInputElement;
    const e = new Date("2020-02-07T12:00:00Z");
    expect(summary.value).toContain(`${pad2(e.getDate())}.${pad2(e.getMonth() + 1)}.${pad2(e.getFullYear() % 100)}`);
  });

  it("H4: смена таймфрейма на 1d переключает подсказку на дневную дату", async () => {
    render(<BacktestPage />);
    await screen.findByText("SBER · Сбербанк");

    toInline('{"timeframe": "1h"}');
    selectByLabel("Инструмент", "1");
    await screen.findByText(hintContains(`Данные для бэктеста доступны с: ${dayLabel("2020-02-07T12:00:00Z")}`));

    toInline('{"timeframe": "1d"}');
    await screen.findByText(hintContains(`Данные для бэктеста доступны с: ${dayLabel("1998-01-01T12:00:00Z")}`));
  });

  it("NULL даты или невыбранный таймфрейм — «источника нет» (поведение MVP-7.5)", async () => {
    render(<BacktestPage />);
    await screen.findByText("SBER · Сбербанк");

    toInline('{"timeframe": "1h"}');
    selectByLabel("Инструмент", "1");
    await screen.findByText(hintContains(`Данные для бэктеста доступны с: ${dayLabel("2020-02-07T12:00:00Z")}`));

    // GAZP: обе даты NULL -> подсказка возвращается к «источника нет».
    selectByLabel("Инструмент", "2");
    await screen.findByText(hintContains("нет данных о доступном диапазоне"));
  });
});
