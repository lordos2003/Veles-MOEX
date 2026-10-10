// @vitest-environment jsdom
/**
 * MVP-8.3: компоненты новой системы — прожектор (R9), skeleton/StatCard (R8),
 * появление с учётом prefers-reduced-motion (R10), ConfirmDialog на Radix (R4).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LazyMotion, MotionConfig, domAnimation } from "motion/react";
import { SpotlightCard } from "./SpotlightCard";
import { Stagger, StaggerItem } from "./Motion";
import { StatCard } from "../StatCard";
import { PageHeader } from "../PageHeader";
import { ConfirmDialog } from "../ConfirmDialog";
import { readFileSync } from "node:fs";

// Состояние prefers-reduced-motion подменяется у useReducedMotion (motion кэширует
// media-запрос при первом использовании, поэтому matchMedia для этого не годится).
const motionState = vi.hoisted(() => ({ reduce: false }));
vi.mock("motion/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("motion/react")>();
  return { ...actual, useReducedMotion: () => motionState.reduce };
});

function stubMatchMedia(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reduce && query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
    onchange: null,
  }));
}

beforeEach(() => {
  stubMatchMedia(false);
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    cb(0);
    return 1;
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SpotlightCard (R9)", () => {
  it("мышь: записывает --mx/--my в стиль карточки", () => {
    const { container } = render(<SpotlightCard>тест</SpotlightCard>);
    const card = container.firstElementChild as HTMLElement;
    card.getBoundingClientRect = () => ({ left: 10, top: 20, width: 100, height: 50, right: 110, bottom: 70, x: 10, y: 20, toJSON: () => ({}) });
    fireEvent.pointerMove(card, { clientX: 40, clientY: 45, pointerType: "mouse" });
    expect(card.style.getPropertyValue("--mx")).toBe("30px");
    expect(card.style.getPropertyValue("--my")).toBe("25px");
  });

  it("touch/pen: координаты не пишутся (эффект только для мыши)", () => {
    const { container } = render(<SpotlightCard>тест</SpotlightCard>);
    const card = container.firstElementChild as HTMLElement;
    fireEvent.pointerMove(card, { clientX: 40, clientY: 45, pointerType: "touch" });
    expect(card.style.getPropertyValue("--mx")).toBe("");
  });

  it("CSS: прожектор включён только для точного указателя и без reduced-motion", () => {
    const css = readFileSync("src/index.css", "utf8");
    expect(css).toMatch(
      /@media \(hover: hover\) and \(pointer: fine\) and \(prefers-reduced-motion: no-preference\)\s*{\s*\.spotlight::before/,
    );
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*transition-duration: 0\.001ms !important/);
  });
});

describe("StatCard (R8)", () => {
  it("загрузка: показывает skeleton, значение скрыто", () => {
    const { container } = render(<StatCard label="Счета" value={3} loading />);
    expect(container.querySelectorAll(".skeleton").length).toBe(2);
    expect(screen.queryByText("3")).toBeNull();
  });

  it("после загрузки: подпись, значение и пояснение", () => {
    render(<StatCard label="Счета" value={3} hint="сохранено: 1" />);
    expect(screen.getByText("Счета")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText("сохранено: 1")).toBeTruthy();
  });
});

describe("PageHeader", () => {
  it("h2 с заголовком, описание и действия", () => {
    render(<PageHeader title="Боты" description="описание" actions={<button>Действие</button>} />);
    expect(screen.getByRole("heading", { level: 2, name: "Боты" })).toBeTruthy();
    expect(screen.getByText("описание")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Действие" })).toBeTruthy();
  });
});

describe("Stagger / StaggerItem и prefers-reduced-motion (R10)", () => {
  function renderStagger(reduce: boolean) {
    motionState.reduce = reduce;
    return render(
      <MotionConfig reducedMotion="user">
        <LazyMotion features={domAnimation} strict>
          <Stagger>
            <StaggerItem>
              <p>блок</p>
            </StaggerItem>
          </Stagger>
        </LazyMotion>
      </MotionConfig>,
    );
  }

  it("без reduced-motion элемент стартует со смещением и появляется (opacity → 1)", async () => {
    const { container } = renderStagger(false);
    const item = container.querySelector("p")!.parentElement as HTMLElement;
    expect(item.style.transform).toContain("translateY");
    await waitFor(() => expect(Number(item.style.opacity)).toBe(1), { timeout: 3000 });
  });

  it("при reduced-motion смещения нет ни в начале, ни в конце (transform пуст или none)", async () => {
    const { container } = renderStagger(true);
    const item = container.querySelector("p")!.parentElement as HTMLElement;
    expect(["", "none"]).toContain(item.style.transform);
    await waitFor(() => expect(Number(item.style.opacity)).toBe(1), { timeout: 3000 });
    expect(["", "none"]).toContain(item.style.transform);
  });
});

describe("ConfirmDialog на Radix Dialog (R4)", () => {
  it("диалог с заголовком и описанием; Esc вызывает onCancel", async () => {
    const onCancel = vi.fn();
    render(
      <ConfirmDialog open title="Удалить?" message={<p>Необратимо</p>} confirmLabel="Удалить" danger onConfirm={() => undefined} onCancel={onCancel} />,
    );
    const dlg = await screen.findByRole("dialog", { name: "Удалить?" });
    expect(dlg.getAttribute("aria-describedby")).toBeTruthy();
    fireEvent.keyDown(dlg, { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();
  });

  it("кнопки «Отмена» и подтверждения работают; закрытый диалог ничего не рисует", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const { rerender } = render(
      <ConfirmDialog open title="Стоп?" message="сообщение" confirmLabel="Да" onConfirm={onConfirm} onCancel={onCancel} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Да" }));
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(1);
    rerender(<ConfirmDialog open={false} title="Стоп?" message="сообщение" confirmLabel="Да" onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("закрытие по Esc возвращает фокус на элемент, открывший диалог (MVP-8.3 LIVE, L9)", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Открыть</button>
          <ConfirmDialog
            open={open}
            title="Удалить?"
            message="сообщение"
            confirmLabel="Удалить"
            onConfirm={() => undefined}
            onCancel={() => setOpen(false)}
          />
        </>
      );
    }
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Открыть" });
    trigger.focus();
    fireEvent.click(trigger);
    const dlg = await screen.findByRole("dialog", { name: "Удалить?" });

    fireEvent.keyDown(dlg, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // Без возврата фокуса активным оставался бы body (Radix Modal фокусит
    // DialogTrigger, которого при управляемом open нет).
    expect(document.activeElement).toBe(trigger);
  });
});
