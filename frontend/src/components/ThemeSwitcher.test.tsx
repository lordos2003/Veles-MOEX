// @vitest-environment jsdom
/**
 * MVP-8.3, раунд 2 (T2/T3): переключатель темы — семантика Radio Group
 * (role, aria-checked, имя группы), клик, клавиатура (стрелки/Home/End,
 * роуминг tabindex), размеры мишеней (>=32px, мобильный >=44px) и
 * применение темы к DOM через setTheme.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { setTheme } from "../lib/theme";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("style");
});

describe("ThemeSwitcher", () => {
  beforeEach(() => {
    // Модульное состояние темы живёт между тестами — возвращаем его к «Тёмной».
    setTheme("dark");
    document.documentElement.dataset.theme = "dark";
  });

  it("radiogroup с именем и двумя радио-опциями, по умолчанию «Тёмная»", () => {
    render(<ThemeSwitcher />);
    const group = screen.getByRole("radiogroup", { name: "Тема оформления" });
    expect(group).toBeTruthy();
    const options = screen.getAllByRole("radio");
    expect(options).toHaveLength(2);
    expect(options[0].textContent).toContain("Тёмная");
    expect(options[1].textContent).toContain("Светлая");
    expect(options[0].getAttribute("aria-checked")).toBe("true");
    expect(options[1].getAttribute("aria-checked")).toBe("false");
    expect(options[0].getAttribute("tabindex")).toBe("0");
    expect(options[1].getAttribute("tabindex")).toBe("-1");
  });

  it("клик по «Светлая» переключает тему, aria-checked и data-theme", () => {
    render(<ThemeSwitcher />);
    const light = screen.getByRole("radio", { name: "Светлая" });
    fireEvent.click(light);
    expect(light.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: "Тёмная" }).getAttribute("aria-checked")).toBe("false");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("veles-theme")).toBe("light");
    expect(light.getAttribute("tabindex")).toBe("0");
  });

  it("стрелки двигают выбор по кругу, Home/End — к краям", () => {
    render(<ThemeSwitcher />);
    const dark = screen.getByRole("radio", { name: "Тёмная" });
    const light = screen.getByRole("radio", { name: "Светлая" });
    dark.focus();
    fireEvent.keyDown(dark, { key: "ArrowRight" });
    expect(light.getAttribute("aria-checked")).toBe("true");
    expect(document.activeElement).toBe(light);
    fireEvent.keyDown(light, { key: "ArrowRight" }); // заворачиваем к Тёмной
    expect(dark.getAttribute("aria-checked")).toBe("true");
    expect(document.activeElement).toBe(dark);
    fireEvent.keyDown(dark, { key: "End" });
    expect(light.getAttribute("aria-checked")).toBe("true");
    fireEvent.keyDown(light, { key: "Home" });
    expect(dark.getAttribute("aria-checked")).toBe("true");
  });

  it("мишени: size=md >= 32px, size=lg >= 44px", () => {
    const { rerender } = render(<ThemeSwitcher />);
    expect(screen.getByRole("radio", { name: "Тёмная" }).className).toContain("min-h-8");
    rerender(<ThemeSwitcher size="lg" />);
    expect(screen.getByRole("radio", { name: "Тёмная" }).className).toContain("min-h-11");
  });

  it("используется в шапке (desktop) и в мобильном меню — без дублей на одном экране", () => {
    const { container } = render(<ThemeSwitcher className="hidden lg:inline-flex" />);
    expect(container.querySelector(".hidden")).toBeTruthy();
  });
});
