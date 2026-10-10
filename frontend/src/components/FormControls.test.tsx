// @vitest-environment jsdom
/**
 * MVP-8.2 live-аудит: Field связывает подпись с любым потомком через контекст,
 * поэтому у чекбокса есть программное имя (aria-label), а заголовок секции
 * идёт сразу после h1/h2 страницы (heading-order).
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CheckboxInput, Field, Section } from "./FormControls";

afterEach(() => cleanup());

describe("FormControls: A2 программные подписи", () => {
  it("CheckboxInput внутри Field получает имя поля", () => {
    render(
      <Field label="Аварийный стоп" required>
        <CheckboxInput value={false} onChange={() => undefined} />
      </Field>,
    );
    expect(screen.getByRole("checkbox", { name: "Аварийный стоп" })).toBeTruthy();
  });

  it("A4 (раунд 2 B1): чекбокс обёрнут в label — кликабельная область 32×32", () => {
    render(
      <Field label="Аварийный стоп">
        <CheckboxInput value={false} onChange={() => undefined} />
      </Field>,
    );
    const box = screen.getByRole("checkbox");
    const wrapper = box.closest("label");
    expect(wrapper).toBeTruthy();
    expect(wrapper!.className).toContain("min-h-8");
    expect(wrapper!.className).toContain("min-w-8");
  });

  it("A4/B4 (раунд 3): обёртка inline-flex без justify-center — чекбокс слева", () => {
    render(
      <Field label="Аварийный стоп">
        <CheckboxInput value={false} onChange={() => undefined} />
      </Field>,
    );
    const wrapper = screen.getByRole("checkbox").closest("label");
    expect(wrapper).toBeTruthy();
    expect(wrapper!.className).toContain("inline-flex");
    expect(wrapper!.className).not.toContain("justify-center");
  });
});

describe("FormControls: heading-order", () => {
  it("Section объявляет заголовок уровня h2", () => {
    render(<Section title="Позиции">содержимое</Section>);
    expect(screen.getByRole("heading", { level: 2, name: "Позиции" })).toBeTruthy();
  });
});
