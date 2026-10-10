// @vitest-environment jsdom
/**
 * MVP-8.3 (R6, R5, R10): оболочка — skip-link и мобильное меню с клавиатуры,
 * ленивые страницы (Suspense-заглушка → страница), заголовок h1 и режим.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LazyMotion, MotionConfig, domAnimation } from "motion/react";
import App from "./App";
import { RuntimeProvider } from "./lib/useRuntime";

function stubMatchMedia(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) => ({
      matches: reduce && query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
      onchange: null,
    }),
  );
}

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.includes("/api/runtime")
        ? { sandbox: true, live_trading_enabled: false, tinvest_configured: true }
        : url.includes("/api/health")
          ? { status: "ok" }
          : url.includes("/api/tinvest/status")
            ? { status: "connected", message: "ok" }
            : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderApp(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RuntimeProvider>
        <MotionConfig reducedMotion="user">
          <LazyMotion features={domAnimation} strict>
            <App />
          </LazyMotion>
        </MotionConfig>
      </RuntimeProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  stubMatchMedia(false);
  stubFetch();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("оболочка приложения", () => {
  it("первый фокусируемый элемент — ссылка «К содержимому» на #main", async () => {
    renderApp();
    const skip = screen.getByRole("link", { name: "К содержимому" });
    expect(skip.getAttribute("href")).toBe("#main");
    expect(document.getElementById("main")).toBeTruthy();
    const focusables = Array.from(document.querySelectorAll<HTMLElement>("a[href], button"));
    expect(focusables[0]).toBe(skip);
    await screen.findByRole("heading", { name: "Обзор" });
  });

  it("h1 — вордмарк со ссылкой на главную, режим «Песочница» виден", async () => {
    renderApp();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Veles");
    expect(screen.getByRole("link", { name: /на главную/ })).toBeTruthy();
    await screen.findByText("Песочница");
  });

  it("страницы грузятся лениво: сначала заглушка, затем содержимое", async () => {
    renderApp("/bots");
    expect(screen.getByRole("status", { name: "Загрузка страницы" })).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "Боты" })).toBeTruthy();
    expect(screen.queryByRole("status", { name: "Загрузка страницы" })).toBeNull();
  });

  it("навигация: все пять разделов, активный помечен aria-current", async () => {
    renderApp("/backtest");
    const nav = screen.getByRole("navigation", { name: "Основная навигация" });
    const links = Array.from(nav.querySelectorAll("a")).map((a) => a.textContent);
    expect(links).toEqual(["Обзор", "Стратегии", "Боты", "Бэктест", "Песочница и счета"]);
    expect(nav.querySelector("a[aria-current='page']")?.textContent).toBe("Бэктест");
    await screen.findByRole("heading", { name: "Бэктест" });
  });

  it("мобильное меню: открывается кнопкой, переход по ссылке закрывает, Esc возвращает фокус", async () => {
    renderApp();
    await screen.findByRole("heading", { name: "Обзор" });
    const open = screen.getByRole("button", { name: "Открыть меню" });
    open.focus();
    fireEvent.click(open);
    const menu = await screen.findByRole("dialog", { name: "Разделы" });
    expect(menu).toBeTruthy();
    expect(screen.getByRole("button", { name: "Закрыть меню" })).toBeTruthy();

    fireEvent.keyDown(menu, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(open);

    fireEvent.click(open);
    const menu2 = await screen.findByRole("dialog", { name: "Разделы" });
    const link = Array.from(menu2.querySelectorAll("a")).find((a) => a.textContent === "Боты")!;
    fireEvent.click(link);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await screen.findByRole("heading", { name: "Боты" });
  });
});
