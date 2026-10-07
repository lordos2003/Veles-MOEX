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
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { StrategyFormPage } from "./StrategyFormPage";

// vitest runs without globals, so @testing-library cannot auto-cleanup.
afterEach(() => cleanup());

const { schemaFixture } = vi.hoisted(() => {
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
  return { schemaFixture };
});

vi.mock("../api", () => ({
  ApiError: class ApiError extends Error {},
  fieldErrors: () => ({}),
  verbatimMessage: (detail: unknown) => String(detail),
  api: {
    get: vi.fn(async (path: string) => {
      if (path === "/api/strategies/schema") return schemaFixture;
      if (path === "/api/strategies/indicators") return [];
      throw new Error(`unexpected path: ${path}`);
    }),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

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

    const lookback = fieldControl("input", /^История,/) as HTMLInputElement;
    expect(lookback.value).toBe("");

    const stopLoss = fieldControl("input", /^Стоп-лосс$/) as HTMLInputElement;
    expect(stopLoss.type).toBe("checkbox");
    expect(stopLoss.checked).toBe(false);
  });
});
