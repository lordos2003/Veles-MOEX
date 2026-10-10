// @vitest-environment jsdom
/**
 * MVP-8.3, раунд 2 (T4): хранилище темы — применение к DOM (data-theme,
 * color-scheme, meta theme-color), localStorage с отказом хранилища,
 * синхронизация между вкладками (storage-событие), тема по умолчанию
 * «Тёмная», а также исполнение внешнего theme-init.js в jsdom.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** Чистый модуль: состояние темы живёт в module-переменной, поэтому тест
 *  пересоздаёт его через resetModules + динамический импорт. */
async function freshTheme() {
  vi.resetModules();
  return import("./theme");
}

function resetDom() {
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("style");
  document.querySelectorAll("meta[name='theme-color'],meta[name='color-scheme']").forEach((m) => m.remove());
}

describe("theme store", () => {
  beforeEach(() => {
    window.localStorage.clear();
    resetDom();
  });

  it("по умолчанию — «Тёмная», даже без сохранённого значения", async () => {
    const theme = await freshTheme();
    expect(theme.getTheme()).toBe("dark");
    expect(theme.DEFAULT_THEME).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("неизвестное значение в localStorage игнорируется (default = dark)", async () => {
    window.localStorage.setItem("veles-theme", "blue");
    const theme = await freshTheme();
    expect(theme.getTheme()).toBe("dark");
  });

  it("setTheme применяет тему к DOM и сохраняет в localStorage", async () => {
    const theme = await freshTheme();
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.appendChild(meta);
    theme.setTheme("light");
    expect(theme.getTheme()).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(window.localStorage.getItem("veles-theme")).toBe("light");
    expect(meta.content).toBe("#f6f7fc");
  });

  it("сбой localStorage не ломает переключение (тема живёт в DOM)", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const theme = await freshTheme();
    expect(theme.getTheme()).toBe("dark");
    expect(() => theme.setTheme("light")).not.toThrow();
    expect(theme.getTheme()).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    vi.restoreAllMocks();
  });

  it("storage-событие синхронизирует тему между вкладками", async () => {
    const theme = await freshTheme();
    theme.setTheme("light");
    window.dispatchEvent(new StorageEvent("storage", { key: "veles-theme", newValue: "dark" }));
    expect(theme.getTheme()).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    // Удаление ключа возвращает тему по умолчанию.
    window.dispatchEvent(new StorageEvent("storage", { key: "veles-theme", newValue: null }));
    expect(theme.getTheme()).toBe("dark");
  });
});

describe("theme-init.js (T4: тема до отрисовки)", () => {
  const code = readFileSync(resolve(process.cwd(), "public/theme-init.js"), "utf8");

  function execInit() {
    // IIFE обращается к window/document как к глобалам jsdom — исполняем как есть.
    new Function(code)();
  }

  beforeEach(() => {
    window.localStorage.clear();
    resetDom();
    const color = document.createElement("meta");
    color.name = "color-scheme";
    color.content = "dark";
    const themeColor = document.createElement("meta");
    themeColor.name = "theme-color";
    themeColor.content = "#0c0e16";
    document.head.append(color, themeColor);
  });

  it("со светлой сохранённой темой ставит data-theme/color-scheme/meta до отрисовки", () => {
    window.localStorage.setItem("veles-theme", "light");
    execInit();
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe("#f6f7fc");
    expect(document.querySelector('meta[name="color-scheme"]')?.getAttribute("content")).toBe("light");
  });

  it("без сохранённой темы остаётся «тёмная» без вспышки", () => {
    execInit();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("сбой localStorage в браузере не мешает скрипту (default = dark)", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => execInit()).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe("dark");
    vi.restoreAllMocks();
  });
});
