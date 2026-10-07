// @vitest-environment jsdom
/**
 * MVP-7.2 I3: при выборе индикатора форма предзаполняет период/параметры из
 * каталога (единственный источник дефолтов I1) и показывает источник значения
 * («по умолчанию (Veles)» / «…(выбор проекта)»), пока пользователь его не
 * изменил. Значения остаются редактируемыми; loaded-конфиг не затирается
 * (предзаполнение только при реальной смене имени).
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { FilterGroupEditor } from "./FilterGroupEditor";
import type { IndicatorResponse } from "../types";

afterEach(() => cleanup());

const CATALOG = new Map<string, IndicatorResponse>([
  [
    "RSI",
    {
      name: "RSI",
      series: ["value"],
      params: [],
      uses_period: true,
      uses_method: false,
      uses_series: false,
      uses_params: false,
      period_default: 14,
      period_default_source: "veles",
    },
  ],
  [
    "MACD",
    {
      name: "MACD",
      series: ["macd", "signal", "histogram"],
      params: [
        { name: "fast", type: "int", required: true, default: 12, default_source: "project" },
        { name: "slow", type: "int", required: true, default: 26, default_source: "project" },
        { name: "signal", type: "int", required: true, default: 9, default_source: "project" },
      ],
      uses_period: false,
      uses_method: false,
      uses_series: true,
      uses_params: true,
      period_default: null,
      period_default_source: null,
    },
  ],
]);

function Harness() {
  const [groups, setGroups] = useState<Record<string, unknown>[]>([
    {
      conditions: [
        {
          arg1: { kind: "indicator", name: "", timeframe: "5m", shift: 0, series: "value", params: {} },
          operator: ">",
          arg2: { kind: "constant", value: 50 },
        },
      ],
    },
  ]);
  return (
    <FilterGroupEditor
      groups={groups}
      onChange={setGroups}
      pathPrefix="entry.groups"
      catalog={CATALOG}
      catalogError={null}
    />
  );
}

function renderEditor() {
  render(<Harness />);
}

/** Label and its control are siblings inside one field div (see form tests).
 * The `<option>` of the arg-kind selector may carry the same text, so the
 * label element is selected explicitly. */
function fieldControl(selector: string, label: RegExp): HTMLInputElement | HTMLSelectElement {
  const cell = screen.getByText(label, { selector: "label" }).parentElement;
  if (!cell) throw new Error(`field cell not found for ${label}`);
  const control = cell.querySelector<HTMLInputElement | HTMLSelectElement>(selector);
  if (!control) throw new Error(`control ${selector} not found for ${label}`);
  return control;
}

function selectIndicator(name: string) {
  const select = fieldControl("select", /^Индикатор$/);
  fireEvent.change(select, { target: { value: name } });
}

describe("MVP-7.2 I3: предзаполнение из каталога и пометка источника", () => {
  it("выбор RSI подставляет период 14 и показывает «по умолчанию (Veles)»", () => {
    renderEditor();
    selectIndicator("RSI");

    const period = fieldControl("input", /^Период$/) as HTMLInputElement;
    expect(period.value).toBe("14");
    expect(screen.getByText("по умолчанию (Veles)")).toBeTruthy();
    // Прочие поля не сбрасываются.
    const timeframe = fieldControl("select", /^Таймфрейм$/) as HTMLSelectElement;
    expect(timeframe.value).toBe("5m");
  });

  it("изменение периода убирает пометку источника (значение больше не «по умолчанию»)", () => {
    renderEditor();
    selectIndicator("RSI");

    const period = fieldControl("input", /^Период$/) as HTMLInputElement;
    fireEvent.change(period, { target: { value: "15" } });
    expect(screen.queryByText("по умолчанию (Veles)")).toBeNull();
  });

  it("выбор MACD подставляет параметры 12/26/9 с пометкой «выбор проекта»; поля периода нет", () => {
    renderEditor();
    selectIndicator("MACD");

    const fast = fieldControl("input", /^fast$/) as HTMLInputElement;
    const slow = fieldControl("input", /^slow$/) as HTMLInputElement;
    const signal = fieldControl("input", /^signal$/) as HTMLInputElement;
    expect(fast.value).toBe("12");
    expect(slow.value).toBe("26");
    expect(signal.value).toBe("9");
    expect(screen.getAllByText("по умолчанию (выбор проекта)")).toHaveLength(3);
    expect(screen.queryByText(/^Период$/)).toBeNull();
  });

  it("изменение параметра убирает его пометку, остальные остаются", () => {
    renderEditor();
    selectIndicator("MACD");

    const fast = fieldControl("input", /^fast$/) as HTMLInputElement;
    fireEvent.change(fast, { target: { value: "13" } });
    expect(screen.getAllByText("по умолчанию (выбор проекта)")).toHaveLength(2);
  });

  it("смена индикатора не затирает выбранный таймфрейм и сдвиг", () => {
    renderEditor();
    selectIndicator("RSI");
    selectIndicator("MACD");

    const timeframe = fieldControl("select", /^Таймфрейм$/) as HTMLSelectElement;
    expect(timeframe.value).toBe("5m");
    const shift = fieldControl("input", /^Сдвиг/) as HTMLInputElement;
    expect(shift.value).toBe("0");
  });
});
