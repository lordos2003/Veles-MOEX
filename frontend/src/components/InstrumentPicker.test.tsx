// @vitest-environment jsdom
/**
 * MVP-8.2 A6: InstrumentPicker is an ARIA combobox — the input exposes
 * aria-expanded/aria-activedescendant, the list is a listbox with options,
 * and the keyboard (ArrowDown/ArrowUp/Enter/Escape) drives the highlight.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { InstrumentPicker } from "./InstrumentPicker";
import type { InstrumentInfo } from "../types";

const INSTS: InstrumentInfo[] = [
  {
    id: 1,
    figi: "BBG004730N88",
    ticker: "SBER",
    name: "Сбербанк",
    instrument_type: "share",
    currency: "RUB",
    lot_size: 10,
    tick_size: "0.01",
    trading_status: "normal_trading",
    exchange: "MOEX",
    is_active: true,
    first_1min_candle_date: null,
    first_1day_candle_date: null,
  },
  {
    id: 2,
    figi: "BBG004730R89",
    ticker: "GAZP",
    name: "Газпром",
    instrument_type: "share",
    currency: "RUB",
    lot_size: 10,
    tick_size: "0.01",
    trading_status: "normal_trading",
    exchange: "MOEX",
    is_active: true,
    first_1min_candle_date: null,
    first_1day_candle_date: null,
  },
];

afterEach(() => cleanup());

describe("InstrumentPicker (MVP-8.2 A6): ARIA combobox и клавиатура", () => {
  it("фокус открывает список; ArrowDown ведёт подсветку, Enter выбирает бумагу", () => {
    const onSelect = vi.fn();
    render(<InstrumentPicker instruments={INSTS} selectedFigi="" onSelect={onSelect} />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    expect(input.getAttribute("aria-expanded")).toBe("false");

    fireEvent.focus(input);
    expect(input.getAttribute("aria-expanded")).toBe("true");
    const listbox = screen.getByRole("listbox");
    expect(listbox).toBeTruthy();
    // Открытие ставит подсветку на первый пункт (highlight=0).
    expect(input.getAttribute("aria-activedescendant")).toContain("option-0");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toContain("option-1");

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("BBG004730R89");
  });

  it("Escape закрывает список; выбранная опция помечена aria-selected", () => {
    const onSelect = vi.fn();
    render(
      <InstrumentPicker
        instruments={INSTS}
        selectedFigi="BBG004730N88"
        onSelect={onSelect}
      />,
    );
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.focus(input);

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(2);
    expect(options[0].getAttribute("aria-selected")).toBe("true");
    expect(options[1].getAttribute("aria-selected")).toBe("false");

    fireEvent.keyDown(input, { key: "Escape" });
    expect(input.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("Tab закрывает список до перехода фокуса (MVP-8.3 LIVE, L9)", () => {
    const onSelect = vi.fn();
    render(
      <InstrumentPicker
        instruments={INSTS}
        selectedFigi=""
        onSelect={onSelect}
      />,
    );
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.focus(input);
    expect(screen.getByRole("listbox")).toBeTruthy();

    fireEvent.keyDown(input, { key: "Tab" });
    expect(input.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});
