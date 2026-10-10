// @vitest-environment jsdom
/**
 * U11 (MVP-7.5): the backtest form sends the picked period as ISO timestamps,
 * and an empty period reports «Укажите период.» without a request.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { api } from "../api";
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

/**
 * The label and the control are siblings inside one field div. Several texts
 * may match the regex (e.g. «Стратегия» matches both the field label and an
 * option label «Стратегия 1»), so take the LABEL element.
 */
function fieldControl(selector: string, label: RegExp): HTMLInputElement | HTMLSelectElement {
  const el = screen.getAllByText(label).find((e) => e.tagName === "LABEL");
  if (!el) throw new Error(`field label not found for ${label}`);
  const cell = el.parentElement;
  if (!cell) throw new Error(`field cell not found for ${label}`);
  const control = cell.querySelector<HTMLInputElement | HTMLSelectElement>(selector);
  if (!control) throw new Error(`control ${selector} not found for ${label}`);
  return control;
}

beforeEach(() => {
  // api spies are shared within the file; call-count assertions need a clean
  // spy on every test regardless of the order they run in.
  vi.mocked(api.post).mockClear();
  vi.mocked(api.get).mockClear();
});

/**
 * MVP-7.7 P1: wait for the «Ценная бумага» picker (the combobox appears only
 * after the instrument list has loaded; before that the field shows
 * «Инструменты не загружены.»).
 */
function pickerInput(): Promise<HTMLInputElement> {
  return screen.findByPlaceholderText("Поиск по тикеру, названию или FIGI…") as Promise<HTMLInputElement>;
}

/** Select a paper in the picker by query (ticker/name) and assert its label. */
function pickInstrument(query: string, expectedLabel: string) {
  const input = screen.getByPlaceholderText("Поиск по тикеру, названию или FIGI…") as HTMLInputElement;
  fireEvent.change(input, { target: { value: query } });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(input.value).toBe(expectedLabel);
}

/** Switch to the inline-config branch with the given JSON. */
function toInline(json: string) {
  fireEvent.click(screen.getByRole("radio", { name: "Инлайн-конфигурация" }));
  const textarea = screen.getByPlaceholderText(
    '{"name": "", "direction": "LONG", "entry": {...}, "exit": {...}}',
  ) as HTMLTextAreaElement;
  fireEvent.change(textarea, { target: { value: json } });
}

function fillRequiredFields() {
  fireEvent.click(screen.getByRole("radio", { name: "Инлайн-конфигурация" }));
  const json = screen.getByPlaceholderText('{"name": "", "direction": "LONG", "entry": {...}, "exit": {...}}');
  fireEvent.change(json, { target: { value: '{"timeframe": "1h"}' } });
  pickInstrument("sber", "SBER — Сбербанк");
  fireEvent.change(screen.getByPlaceholderText("например, 100000"), { target: { value: "100000" } });
}

describe("BacktestPage: U11 период", () => {
  it("пустой период: ошибка у поля, запрос не уходит", async () => {
    const { api } = await import("../api");
    render(<BacktestPage />);
    await pickerInput();
    fillRequiredFields();

    fireEvent.click(screen.getByRole("button", { name: "Запустить бэктест" }));
    expect(screen.getByText("Укажите период.")).toBeTruthy();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("выбранный период уходит в запросе ISO-строками", async () => {
    const { api } = await import("../api");
    render(<BacktestPage />);
    await pickerInput();
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
    // MVP-7.7 P1/P3: the picked paper id and the default fees travel together.
    expect(payload.instrument_id).toBe(1);
    expect(payload.maker_fee).toBe("0.003");
    expect(payload.taker_fee).toBe("0.003");
    expect(payload.slippage).toBe("0.001");
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

  it("H4: 1h берёт дату первой минутной свечи; «Весь период» от earliest", async () => {
    render(<BacktestPage />);
    await pickerInput();

    toInline('{"timeframe": "1h"}');
    pickInstrument("sber", "SBER — Сбербанк");

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
    await pickerInput();

    toInline('{"timeframe": "1h"}');
    pickInstrument("sber", "SBER — Сбербанк");
    await screen.findByText(hintContains(`Данные для бэктеста доступны с: ${dayLabel("2020-02-07T12:00:00Z")}`));

    toInline('{"timeframe": "1d"}');
    await screen.findByText(hintContains(`Данные для бэктеста доступны с: ${dayLabel("1998-01-01T12:00:00Z")}`));
  });

  it("NULL даты или невыбранный таймфрейм — «источника нет» (поведение MVP-7.5)", async () => {
    render(<BacktestPage />);
    await pickerInput();

    toInline('{"timeframe": "1h"}');
    pickInstrument("sber", "SBER — Сбербанк");
    await screen.findByText(hintContains(`Данные для бэктеста доступны с: ${dayLabel("2020-02-07T12:00:00Z")}`));

    // GAZP: обе даты NULL -> подсказка возвращается к «источника нет».
    pickInstrument("газ", "GAZP — Газпром");
    await screen.findByText(hintContains("нет данных о доступном диапазоне"));
  });
});

describe("MVP-7.7 P1/P2: «Ценная бумага» — единый поиск в форме бэктеста", () => {
  it("выбор по названию уходит instrument_id бумаги в POST /api/backtests", async () => {
    const { api } = await import("../api");
    render(<BacktestPage />);
    await pickerInput();

    fireEvent.click(screen.getByRole("radio", { name: "Инлайн-конфигурация" }));
    fireEvent.change(
      screen.getByPlaceholderText('{"name": "", "direction": "LONG", "entry": {...}, "exit": {...}}'),
      { target: { value: '{"timeframe": "1h"}' } },
    );
    // По названию, не по тикеру.
    pickInstrument("газпром", "GAZP — Газпром");
    fireEvent.change(screen.getByPlaceholderText("например, 100000"), { target: { value: "100000" } });

    const now = new Date();
    const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    fireEvent.click(screen.getByLabelText("Открыть календарь"));
    fireEvent.click(screen.getByLabelText("Предыдущий месяц"));
    fireEvent.click(screen.getByRole("button", { name: `5.${prev.getMonth() + 1}.${prev.getFullYear()}` }));
    fireEvent.click(screen.getByRole("button", { name: `7.${prev.getMonth() + 1}.${prev.getFullYear()}` }));
    fireEvent.click(screen.getByRole("button", { name: "Запустить бэктест" }));

    const post = api.post as unknown as ReturnType<typeof vi.fn>;
    expect(post).toHaveBeenCalledTimes(1);
    const [path, payload] = post.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/api/backtests");
    expect(payload.instrument_id).toBe(2);
  });

  it("пустой выбор — ошибка у поля «Ценная бумага», запрос не уходит", async () => {
    const { api } = await import("../api");
    render(<BacktestPage />);
    await pickerInput();

    fireEvent.click(screen.getByRole("radio", { name: "Инлайн-конфигурация" }));
    fireEvent.change(
      screen.getByPlaceholderText('{"name": "", "direction": "LONG", "entry": {...}, "exit": {...}}'),
      { target: { value: '{"timeframe": "1h"}' } },
    );
    fireEvent.change(screen.getByPlaceholderText("например, 100000"), { target: { value: "100000" } });

    fireEvent.click(screen.getByRole("button", { name: "Запустить бэктест" }));
    expect(screen.getByText("Выберите ценную бумагу.")).toBeTruthy();
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe("MVP-7.7 P3: комиссии и проскальзывание по умолчанию", () => {
  it("поля при открытии содержат 0.003 / 0.003 / 0.001, депозит пуст", async () => {
    render(<BacktestPage />);
    await pickerInput();

    const maker = fieldControl("input", /Maker-комиссия/) as HTMLInputElement;
    const taker = fieldControl("input", /Taker-комиссия/) as HTMLInputElement;
    const slip = fieldControl("input", /Проскальзывание/) as HTMLInputElement;
    const deposit = fieldControl("input", /Депозит сделки/) as HTMLInputElement;
    expect(maker.value).toBe("0.003");
    expect(taker.value).toBe("0.003");
    expect(slip.value).toBe("0.001");
    expect(deposit.value).toBe("");
  });

  it("плейсхолдеры «например, 0.0003/0.001» убраны, подсказка обновлена", async () => {
    render(<BacktestPage />);
    await pickerInput();

    expect(screen.queryByPlaceholderText("например, 0.0003")).toBeNull();
    expect(screen.queryByPlaceholderText("например, 0.001")).toBeNull();
    expect(screen.getByText(/Комиссии задаются долей \(например, 0\.003 = 0\.3%\)\./)).toBeTruthy();
    expect(screen.queryByText(/не подставляются автоматически/)).toBeNull();
  });

  it("введённые пользователем значения не сбрасываются при смене бумаги и таймфрейма", async () => {
    render(<BacktestPage />);
    await pickerInput();

    const maker = fieldControl("input", /Maker-комиссия/) as HTMLInputElement;
    fireEvent.change(maker, { target: { value: "0.005" } });

    toInline('{"timeframe": "1h"}');
    pickInstrument("sber", "SBER — Сбербанк");
    // Смена таймфрейма и бумаги не трогает введённое значение.
    expect(maker.value).toBe("0.005");
    toInline('{"timeframe": "1d"}');
    pickInstrument("газ", "GAZP — Газпром");
    expect(maker.value).toBe("0.005");
  });

  it("в POST /api/backtests уходят введённые пользователем значения", async () => {
    const { api } = await import("../api");
    render(<BacktestPage />);
    await pickerInput();

    const maker = fieldControl("input", /Maker-комиссия/) as HTMLInputElement;
    const taker = fieldControl("input", /Taker-комиссия/) as HTMLInputElement;
    const slip = fieldControl("input", /Проскальзывание/) as HTMLInputElement;
    fireEvent.change(maker, { target: { value: "0.005" } });
    fireEvent.change(taker, { target: { value: "0.004" } });
    fireEvent.change(slip, { target: { value: "0.002" } });
    fillRequiredFields();

    const now = new Date();
    const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    fireEvent.click(screen.getByLabelText("Открыть календарь"));
    fireEvent.click(screen.getByLabelText("Предыдущий месяц"));
    fireEvent.click(screen.getByRole("button", { name: `5.${prev.getMonth() + 1}.${prev.getFullYear()}` }));
    fireEvent.click(screen.getByRole("button", { name: `7.${prev.getMonth() + 1}.${prev.getFullYear()}` }));
    fireEvent.click(screen.getByRole("button", { name: "Запустить бэктест" }));

    const post = api.post as unknown as ReturnType<typeof vi.fn>;
    expect(post).toHaveBeenCalledTimes(1);
    const [path, payload] = post.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/api/backtests");
    expect(payload.maker_fee).toBe("0.005");
    expect(payload.taker_fee).toBe("0.004");
    expect(payload.slippage).toBe("0.002");
  });
});

describe("MVP-8.2 A2: программные подписи всех полей бэктеста", () => {
  it("селекты и текстовые поля доступны по имени", async () => {
    render(<BacktestPage />);
    await pickerInput();
    expect(screen.getByLabelText("Стратегия")).toBeTruthy();
    expect(screen.getByLabelText("Версия")).toBeTruthy();
    expect(screen.getByLabelText("Ценная бумага")).toBeTruthy();
    expect(screen.getByLabelText("Таймфрейм (из конфигурации)")).toBeTruthy();
    expect(screen.getByLabelText("Период")).toBeTruthy();
    expect(screen.getByLabelText("Депозит сделки")).toBeTruthy();
    expect(screen.getByLabelText("Maker-комиссия")).toBeTruthy();
    expect(screen.getByLabelText("Taker-комиссия")).toBeTruthy();
    expect(screen.getByLabelText("Проскальзывание")).toBeTruthy();
  });

  it("textarea инлайн-конфигурации имеет имя", async () => {
    render(<BacktestPage />);
    await pickerInput();
    fireEvent.click(screen.getByRole("radio", { name: "Инлайн-конфигурация" }));
    expect(screen.getByLabelText("Конфигурация (JSON)")).toBeTruthy();
  });

  it("список бумаг — listbox с option и активной строкой", async () => {
    render(<BacktestPage />);
    const input = await pickerInput();
    fireEvent.focus(input);
    expect(screen.getByRole("listbox")).toBeTruthy();
    const options = screen.getAllByRole("option");
    expect(options.length).toBeGreaterThanOrEqual(2);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toBeTruthy();
  });
});
