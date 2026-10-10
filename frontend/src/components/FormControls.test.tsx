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
});

describe("FormControls: heading-order", () => {
  it("Section объявляет заголовок уровня h2", () => {
    render(<Section title="Позиции">содержимое</Section>);
    expect(screen.getByRole("heading", { level: 2, name: "Позиции" })).toBeTruthy();
  });
});
