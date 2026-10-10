/**
 * MVP-8.3, раунд 2 (T1/T8): интеграционная проверка, что check:contrast
 * разбирает ОБЕ темы (токены @theme и переопределения data-theme="light")
 * и не имеет нарушений (4.5:1 текст, 3:1 границы/фокус по 1.4.11).
 * Скрипт запускается в node из корня frontend (cwd vitest = корень пакета).
 */
import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";

describe("check:contrast (обе темы)", () => {
  it("проходит с 0 нарушений в тёмной и светлой темах", () => {
    const output = execFileSync(process.execPath, ["scripts/check-contrast.mjs"], {
      cwd: process.cwd(),
      encoding: "utf8",
      timeout: 60_000,
    });
    expect(output).toContain("=== Тема: ТЁМНАЯ ===");
    expect(output).toContain("=== Тема: СВЕТЛАЯ ===");
    expect(output).toContain("--- 1.4.11 (границы/фокус, >= 3:1) ---");
    expect(output).toContain("ИТОГ: 0 нарушений");
  });
});
