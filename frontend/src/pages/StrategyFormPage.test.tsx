// @vitest-environment jsdom
/**
 * REV2 B4 (page-level test): a NEW strategy form must start from schema
 * defaults, including a `default` that sits BESIDE a `$ref` (real pydantic
 * shape). The unit test for `initialValue` did not catch the page bug: the
 * loading effect set `loaded=true` immediately for a new strategy, so the
 * schema-init effect never ran and every field looked "not selected".
 *
 * The `Field` wrapper renders the label and the control as siblings (no
 * htmlFor/id), so controls are located through their field cell, not by
 * accessible name.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ApiError, api } from "../api";
import { StrategyFormPage } from "./StrategyFormPage";

// vitest runs without globals, so @testing-library cannot auto-cleanup.
afterEach(() => cleanup());

const { schemaFixture, instruments } = vi.hoisted(() => {
  const instruments = [
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
  ];
  const schemaFixture = {
    title: "StrategyConfig",
    $defs: {
      Direction: { type: "string", enum: ["LONG", "SHORT"] },
      CalculationMethod: { type: "string", enum: ["at_bar_close", "per_minute"] },
      TradingMode: { type: "string", enum: ["simple", "custom", "signal"] },
      Timeframe: {
        type: "string",
        enum: ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"],
      },
      FilterGroup: {
        type: "object",
        properties: {
          id: { type: "string" },
          conditions: { type: "array", items: { type: "object" } },
        },
      },
      EntryConfig: {
        type: "object",
        properties: {
          method: { $ref: "#/$defs/CalculationMethod", default: "at_bar_close" },
          groups: { type: "array", items: { $ref: "#/$defs/FilterGroup" } },
        },
        required: ["method"],
      },
      DCAGridConfig: {
        type: "object",
        properties: {
          mode: { $ref: "#/$defs/TradingMode", default: "simple" },
          levels: { type: "integer", default: 1, minimum: 1 },
          overlap_percent: { type: "number", default: 0.0 },
        },
      },
      ExitConfig: {
        type: "object",
        properties: {
          take_profit: {
            oneOf: [
              {
                type: "object",
                properties: {
                  kind: { type: "string", const: "fixed_percentage" },
                  percent: { type: "number" },
                },
                required: ["kind", "percent"],
              },
            ],
            discriminator: { propertyName: "kind" },
          },
          stop_loss: { anyOf: [{ $ref: "#/$defs/StopLossConfig" }, { type: "null" }], default: null },
          signal_stop: { anyOf: [{ type: "object" }, { type: "null" }], default: null },
        },
        required: ["take_profit"],
      },
      StopLossConfig: {
        type: "object",
        properties: {
          kind: { type: "string", const: "percent" },
          percent: { type: "number" },
          stop_bot_after: { anyOf: [{ type: "boolean" }, { type: "null" }], default: null },
        },
        required: ["kind", "percent"],
      },
      RiskConfig: {
        type: "object",
        properties: {
          emergency_stop: { type: "boolean", default: false },
          max_position_size: { anyOf: [{ type: "number" }, { type: "null" }], default: null },
        },
      },
    },
    type: "object",
    properties: {
      name: { type: "string", default: "" },
      direction: { $ref: "#/$defs/Direction", default: "LONG" },
      timeframe: { anyOf: [{ $ref: "#/$defs/Timeframe" }, { type: "null" }], default: null },
      lookback_bars: { anyOf: [{ type: "integer" }, { type: "null" }] },
      entry: { $ref: "#/$defs/EntryConfig" },
      dca_grid: { $ref: "#/$defs/DCAGridConfig" },
      exit: { $ref: "#/$defs/ExitConfig" },
      risk: { $ref: "#/$defs/RiskConfig" },
    },
  };
  return { schemaFixture, instruments };
});

const savedStrategy = {
  id: 7,
  name: "Тестовая",
  description: "",
  is_active: false,
  versions: 1,
  created_at: null,
  updated_at: null,
  config: {
    name: "Тестовая",
    direction: "LONG",
    timeframe: "1m",
    instrument_id: 2,
    entry: { method: "at_bar_close", groups: [] },
    dca_grid: { mode: "simple", levels: 1, overlap_percent: 0.0 },
    exit: { take_profit: { kind: "fixed_percentage", percent: 10.0 } },
    risk: {},
  },
};

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      get: vi.fn(async (path: string) => {
        if (path === "/api/strategies/schema") return schemaFixture;
        if (path === "/api/strategies/indicators") return [];
        if (path === "/api/instruments?active=true") return instruments;
        if (path === "/api/strategies/7") return savedStrategy;
        throw new Error(`unexpected path: ${path}`);
      }),
      post: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  };
});

/** The label and the control are siblings inside one field div. */
function fieldControl(selector: string, label: RegExp): HTMLInputElement | HTMLSelectElement {
  const cell = screen.getByText(label).parentElement;
  if (!cell) throw new Error(`field cell not found for ${label}`);
  const control = cell.querySelector<HTMLInputElement | HTMLSelectElement>(selector);
  if (!control) throw new Error(`control ${selector} not found for ${label}`);
  return control;
}

function renderNewStrategy() {
  return render(
    <MemoryRouter initialEntries={["/strategies/new"]}>
      <Routes>
        <Route path="/strategies/new" element={<StrategyFormPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("REV2 B4: новая форма стратегии берёт значения по умолчанию из схемы", () => {
  it("показывает «Направление» = Лонг, «Метод расчёта» = По закрытию бара, «Режим» = Простой", async () => {
    renderNewStrategy();
    await screen.findByRole("heading", { name: "Новая стратегия" });

    const direction = fieldControl("select", /Направление/) as HTMLSelectElement;
    expect(direction.value).toBe("LONG");
    expect(direction.options[direction.selectedIndex]?.textContent).toBe("Лонг");

    const method = fieldControl("select", /Метод расчёта/) as HTMLSelectElement;
    expect(method.value).toBe("at_bar_close");
    expect(method.options[method.selectedIndex]?.textContent).toBe("По закрытию бара");

    const mode = fieldControl("select", /Режим/) as HTMLSelectElement;
    expect(mode.value).toBe("simple");
    expect(mode.options[mode.selectedIndex]?.textContent).toBe("Простой");
  });

  it("подставляет в форму числовые defaults: Уровней = 1, Перекрытие = 0", async () => {
    renderNewStrategy();
    await screen.findByRole("heading", { name: "Новая стратегия" });

    const levels = fieldControl("input", /Уровней/) as HTMLInputElement;
    expect(levels.value).toBe("1");

    const overlap = fieldControl("input", /^Перекрытие/) as HTMLInputElement;
    expect(overlap.value).toBe("0");
  });

  it("поля без default в схеме остаются пустыми; стоп-лосс не выбран", async () => {
    renderNewStrategy();
    await screen.findByRole("heading", { name: "Новая стратегия" });

    const picker = fieldControl("input", /Ценная бумага/) as HTMLInputElement;
    expect(picker.value).toBe("");

    const stopLoss = fieldControl("input", /^Стоп-лосс$/) as HTMLInputElement;
    expect(stopLoss.type).toBe("checkbox");
    expect(stopLoss.checked).toBe(false);
  });

  it("U10: поля «История, баров» в форме нет и оно не попадает в «Дополнительные поля»", async () => {
    renderNewStrategy();
    await screen.findByRole("heading", { name: "Новая стратегия" });

    expect(screen.queryByText(/История, баров/)).toBeNull();
    expect(screen.queryByText(/Дополнительные поля/)).toBeNull();
  });
});

describe("MVP-7.5 U9: «Ценная бумага»", () => {
  it("выбор по тикеру записывает верный instrument_id и показывает подпись", async () => {
    const post = vi.mocked(api.post);
    post.mockResolvedValue({ valid: true, live_deal: { supported: true, reason: null } });
    renderNewStrategy();
    await screen.findByRole("heading", { name: "Новая стратегия" });

    const input = fieldControl("input", /Ценная бумага/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "газпром" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    // The field shows the paper label (U3 format), the config keeps the id.
    expect(input.value).toBe("GAZP — Газпром");
    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));
    await screen.findByText("Для живой торговли подходит.");
    const body = post.mock.calls.find(([p]) => p === "/api/strategies/validate")?.[1] as
      | Record<string, unknown>
      | undefined;
    expect(body?.instrument_id).toBe(2);
  });

  it("пустой выбор — ошибка бэкенда привязана к полю «Ценная бумага»", async () => {
    vi.mocked(api.post).mockRejectedValue(
      new ApiError(422, {
        detail: [
          {
            type: "missing",
            loc: ["body", "instrument_id"],
            msg: "Field required",
            input: {},
          },
        ],
      }),
    );
    renderNewStrategy();
    await screen.findByRole("heading", { name: "Новая стратегия" });

    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));
    await screen.findByText("Ценная бумага: Field required");

    const cell = screen
      .getByText(
        (content, el) => el?.tagName === "LABEL" && content.startsWith("Ценная бумага"),
      )
      .parentElement;
    expect(cell?.textContent).toContain("Field required");
  });

  it("существующая стратегия открывается с подписью бумаги, а не с числом", async () => {
    render(
      <MemoryRouter initialEntries={["/strategies/7/edit"]}>
        <Routes>
          <Route path="/strategies/:id/edit" element={<StrategyFormPage edit />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { name: "Стратегия — редактирование" });

    const input = fieldControl("input", /Ценная бумага/) as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("GAZP — Газпром"));
  });
});

describe("MVP-7.4 U5/U6: кнопка «Проверить»", () => {
  it("U5: шлёт голый конфиг (без обёртки { config }) и показывает вердикт live_deal", async () => {
    const post = vi.mocked(api.post);
    post.mockResolvedValue({ valid: true, live_deal: { supported: true, reason: null } });
    renderNewStrategy();
    await screen.findByRole("heading", { name: "Новая стратегия" });

    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));
    await screen.findByText("Для живой торговли подходит.");

    expect(post).toHaveBeenCalledWith("/api/strategies/validate", expect.any(Object));
    const body = post.mock.calls[0][1] as Record<string, unknown>;
    expect(body).not.toHaveProperty("config");
    expect(body).toHaveProperty("entry");
  });

  it("U6: ошибка «не выбран вид тейк-профита» — у поля «Тейк-профит» и читаемый баннер", async () => {
    vi.mocked(api.post).mockRejectedValue(
      new ApiError(422, {
        detail: [
          {
            type: "missing",
            loc: ["body", "exit", "take_profit"],
            msg: "Field required",
            input: {},
          },
        ],
      }),
    );
    renderNewStrategy();
    await screen.findByRole("heading", { name: "Новая стратегия" });

    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));

    // Баннер в формате «поле: сообщение», без сырого JSON-списка.
    await screen.findByText("Тейк-профит: Field required");

    // Сообщение привязано к полю «Тейк-профит».
    const cell = screen
      .getByText(
        (content, el) => el?.tagName === "LABEL" && content.startsWith("Тейк-профит"),
      )
      .parentElement;
    expect(cell?.textContent).toContain("Field required");
  });
});
