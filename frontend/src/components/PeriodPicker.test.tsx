// @vitest-environment jsdom
/**
 * U11 (MVP-7.5): the «Период» picker — range clicks, manual date/time input,
 * quick presets (frozen "now"), Esc close and the summary format.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PeriodPicker } from "./PeriodPicker";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/** Stateful wrapper: the picker is controlled, so chained clicks need state. */
function Harness(props: { earliestAvailable?: string; onChange: (from: Date | null, to: Date | null) => void }) {
  const [from, setFrom] = useState<Date | null>(null);
  const [to, setTo] = useState<Date | null>(null);
  return (
    <PeriodPicker
      from={from}
      to={to}
      earliestAvailable={props.earliestAvailable}
      onChange={(f, t) => {
        setFrom(f);
        setTo(t);
        props.onChange(f, t);
      }}
    />
  );
}

function openPanel() {
  fireEvent.click(screen.getByLabelText("Период"));
}

describe("PeriodPicker: календарь", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Frozen "now": 08.10.2026 16:19 local.
    vi.setSystemTime(new Date(2026, 9, 8, 16, 19));
  });

  it("выбор двух дней задаёт диапазон и показывает сводку", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    openPanel();

    expect(screen.getByText("октябрь 2026")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "5.10.2026" }));
    expect(onChange).toHaveBeenLastCalledWith(new Date(2026, 9, 5), null);

    fireEvent.click(screen.getByRole("button", { name: "7.10.2026" }));
    expect(onChange).toHaveBeenLastCalledWith(new Date(2026, 9, 5), new Date(2026, 9, 7));
    expect((screen.getByLabelText("Период") as HTMLInputElement).value).toBe("05.10.26 0:00 - 07.10.26 0:00");
  });

  it("выбор по возрастанию выделяет диапазон, Esc закрывает панель", () => {
    const onChange = vi.fn();
    const { container } = render(<PeriodPicker from={new Date(2026, 9, 5)} to={new Date(2026, 9, 7)} onChange={onChange} />);
    openPanel();

    const between = container.querySelector(".bg-accent-soft\\/70");
    expect(between).toBeTruthy();

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByLabelText("Дата начала")).toBeNull();
  });

  it("стрелки листают месяцы", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} />);
    openPanel();
    fireEvent.click(screen.getByLabelText("Предыдущий месяц"));
    expect(screen.getByText("сентябрь 2026")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Следующий месяц"));
    expect(screen.getByText("октябрь 2026")).toBeTruthy();
  });

  it("ручной ввод даты и времени синхронизируется с выбором", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    openPanel();

    fireEvent.change(screen.getByLabelText("Дата начала"), { target: { value: "01.10.2026" } });
    // Только дата — пара не полная, коммита быть не должно.
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Время начала"), { target: { value: "7:21" } });
    expect(onChange).toHaveBeenLastCalledWith(new Date(2026, 9, 1, 7, 21), null);

    fireEvent.change(screen.getByLabelText("Дата конца"), { target: { value: "07.10.2026" } });
    fireEvent.change(screen.getByLabelText("Время конца"), { target: { value: "16:19" } });
    expect(onChange).toHaveBeenLastCalledWith(new Date(2026, 9, 1, 7, 21), new Date(2026, 9, 7, 16, 19));
  });
});

describe("PeriodPicker: быстрые пресеты", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 8, 16, 19));
  });

  it("«Месяц» = −1 календарный месяц от текущего момента", () => {
    const onChange = vi.fn();
    render(<PeriodPicker from={null} to={null} onChange={onChange} earliestAvailable="2026-09-01" />);
    fireEvent.click(screen.getByRole("button", { name: "Быстрый выбор периода" }));
    fireEvent.click(screen.getByRole("button", { name: /Месяц/ }));

    expect(onChange).toHaveBeenCalledWith(new Date(2026, 8, 8, 16, 19), new Date(2026, 9, 8, 16, 19));
  });

  it("«Год»/«3 года» скрыты, когда история короче", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} earliestAvailable="2026-06-01" />);
    fireEvent.click(screen.getByRole("button", { name: "Быстрый выбор периода" }));

    expect(screen.getByRole("button", { name: /Месяц/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /3 месяца/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Год/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /3 года/ })).toBeNull();
    expect(screen.getAllByRole("button", { name: /Весь период/ }).length).toBe(1);
  });

  it("«Весь период» начинается с самой ранней даты", () => {
    const onChange = vi.fn();
    render(<PeriodPicker from={null} to={null} onChange={onChange} earliestAvailable="2025-03-17" />);
    fireEvent.click(screen.getByRole("button", { name: "Быстрый выбор периода" }));
    fireEvent.click(screen.getByRole("button", { name: /Весь период/ }));

    expect(onChange).toHaveBeenCalledWith(new Date(2025, 2, 17), new Date(2026, 9, 8, 16, 19));
    // U13: календарь закрыт при открытых пресетах — подсказка снова в календаре.
    fireEvent.click(screen.getByLabelText("Период"));
    expect(screen.getByText("Данные для бэктеста доступны с: 17.03.2025")).toBeTruthy();
  });

  it("без источника ранней даты «Весь период» отключён", () => {
    const onChange = vi.fn();
    render(<PeriodPicker from={null} to={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Быстрый выбор периода" }));

    const all = screen.getByRole("button", { name: /Весь период/ }) as HTMLButtonElement;
    expect(all.disabled).toBe(true);
    fireEvent.click(all);
    expect(onChange).not.toHaveBeenCalled();
    // Пояснение видно у пресета (календарь закрыт — подсказка там не видна).
    expect(screen.getAllByText("нет данных о доступном диапазоне").length).toBe(1);
  });
});

describe("PeriodPicker: U13 (раунд 2) — календарь по датам, пресеты по значку", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 8, 16, 19));
  });

  it("клик по полю дат открывает календарь без пресетов", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} />);
    openPanel();

    expect(screen.getByRole("dialog", { name: "Выбор периода" })).toBeTruthy();
    expect(screen.getByText("октябрь 2026")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Месяц/ })).toBeNull();
  });

  it("клик по значку открывает пресеты без календаря", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Быстрый выбор периода" }));

    expect(screen.getByRole("button", { name: /Месяц/ })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByLabelText("Дата начала")).toBeNull();
  });

  it("одновременно открыт один попап: значок закрывает календарь и наоборот", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} />);
    openPanel();
    expect(screen.getByRole("dialog")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Быстрый выбор периода" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: /Месяц/ })).toBeTruthy();

    fireEvent.click(screen.getByLabelText("Период"));
    expect(screen.queryByRole("button", { name: /Месяц/ })).toBeNull();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("Esc с поля закрывает календарь и возвращает фокус на поле", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} />);
    openPanel();
    expect(screen.getByRole("dialog")).toBeTruthy();

    const input = screen.getByLabelText("Период") as HTMLInputElement;
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(input);
  });

  it("Esc с кнопки-значка закрывает пресеты и возвращает фокус на значок", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} />);
    const icon = screen.getByRole("button", { name: "Быстрый выбор периода" });
    fireEvent.click(icon);
    expect(screen.getByRole("button", { name: /Месяц/ })).toBeTruthy();

    fireEvent.keyDown(icon, { key: "Escape" });
    expect(screen.queryByRole("button", { name: /Месяц/ })).toBeNull();
    expect(document.activeElement).toBe(icon);
  });

  it("нет видимого текста «Быстрый выбор» (остался только aria-label значка)", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} />);
    expect(screen.queryByText(/Быстрый выбор/)).toBeNull();
  });

  it("поле открывает календарь по Enter, Space и ↓", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} />);
    const input = screen.getByLabelText("Период");

    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(input, { key: "Escape" });

    fireEvent.keyDown(input, { key: " " });
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(input, { key: "Escape" });

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("внутри пресетов ↓/↑ двигают фокус по опциям", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Быстрый выбор периода" }));

    const first = screen.getByRole("button", { name: /Месяц/ }) as HTMLButtonElement;
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /3 месяца/ }));

    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "ArrowUp" });
    expect(document.activeElement).toBe(first);
  });

  it("M7 (раунд 3): выбор пресета возвращает фокус на значок", () => {
    render(<PeriodPicker from={null} to={null} onChange={() => {}} />);
    const icon = screen.getByRole("button", { name: "Быстрый выбор периода" });
    fireEvent.click(icon);
    expect(screen.getByRole("button", { name: /Месяц/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Месяц/ }));
    expect(screen.queryByRole("button", { name: /Месяц/ })).toBeNull();
    expect(document.activeElement).toBe(icon);
  });
});
