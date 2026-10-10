import { createContext, useContext } from "react";
import type { ReactNode } from "react";

/**
 * MVP-8.2 A2: Field renders a visible label and passes its text down; every
 * form control inside associates itself via aria-label. This keeps the page
 * markup unchanged (Field children are arbitrary components) while giving
 * each control a programmatic name. The marker/hint stay inside the visible
 * label element, so the accessible name is the clean label text.
 */
const FieldLabelContext = createContext<string | null>(null);

export function useFieldLabel(): string | null {
  return useContext(FieldLabelContext);
}

/** Labeled field wrapper: label, optional hint, error line (for 422 paths). */
export function Field(props: {
  label: string;
  hint?: string | null;
  error?: string | null;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="block text-sm font-medium text-text-secondary">
        {props.label}
        {props.required ? <span className="ml-1 text-amber-400">*</span> : null}
        {props.hint ? (
          <span className="ml-2 text-xs font-normal text-text-muted" title={props.hint}>
            ⓘ {props.hint}
          </span>
        ) : null}
      </label>
      <FieldLabelContext.Provider value={props.label}>{props.children}</FieldLabelContext.Provider>
      {props.error ? <p className="text-xs text-red-400">{props.error}</p> : null}
    </div>
  );
}

const inputClass =
  "min-h-9 w-full rounded-control border border-zinc-700 bg-zinc-900/70 px-3 py-1.5 text-sm text-text " +
  "transition-colors duration-(--duration-fast) hover:border-zinc-600 focus:border-accent-bright disabled:opacity-50";

export function TextInput(props: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  const fieldLabel = useFieldLabel();
  return (
    <input
      type="text"
      className={inputClass}
      value={props.value}
      disabled={props.disabled}
      placeholder={props.placeholder}
      onChange={(e) => props.onChange(e.target.value)}
      aria-label={fieldLabel ?? undefined}
    />
  );
}

export function TextareaInput(props: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  spellCheck?: boolean;
  className?: string;
}) {
  const fieldLabel = useFieldLabel();
  return (
    <textarea
      className={`min-h-9 w-full rounded-control border border-zinc-700 bg-zinc-950 p-3 text-xs font-mono text-zinc-200 transition-colors duration-(--duration-fast) hover:border-zinc-600 focus:border-accent-bright ${props.className ?? ""}`}
      value={props.value}
      placeholder={props.placeholder}
      spellCheck={props.spellCheck ?? false}
      onChange={(e) => props.onChange(e.target.value)}
      aria-label={fieldLabel ?? undefined}
    />
  );
}

export function NumberInput(props: {
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  placeholder?: string;
  disabled?: boolean;
  step?: string;
}) {
  const fieldLabel = useFieldLabel();
  return (
    <input
      type="number"
      step={props.step ?? "any"}
      className={inputClass}
      value={props.value === null || props.value === undefined ? "" : String(props.value)}
      disabled={props.disabled}
      placeholder={props.placeholder}
      onChange={(e) => {
        const raw = e.target.value;
        if (raw === "") {
          props.onChange(null);
          return;
        }
        const parsed = Number(raw);
        props.onChange(Number.isNaN(parsed) ? null : parsed);
      }}
      aria-label={fieldLabel ?? undefined}
    />
  );
}

export function SelectInput(props: {
  value: unknown;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  allowEmpty?: boolean;
  emptyLabel?: string;
  disabled?: boolean;
}) {
  const fieldLabel = useFieldLabel();
  const value = props.value === null || props.value === undefined ? "" : String(props.value);
  return (
    <select
      className={inputClass}
      value={value}
      disabled={props.disabled}
      onChange={(e) => props.onChange(e.target.value)}
      aria-label={fieldLabel ?? undefined}
    >
      {props.allowEmpty ? <option value="">{props.emptyLabel ?? "— не выбрано —"}</option> : null}
      {props.options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/** Nullable boolean: explicit "не выбрано" / да / нет (never implicit false). */
export function NullableBoolInput(props: {
  value: boolean | null | undefined;
  onChange: (value: boolean | null) => void;
  disabled?: boolean;
}) {
  const fieldLabel = useFieldLabel();
  const current = props.value === true ? "true" : props.value === false ? "false" : "";
  return (
    <select
      className={inputClass}
      value={current}
      disabled={props.disabled}
      onChange={(e) => {
        if (e.target.value === "") props.onChange(null);
        else if (e.target.value === "true") props.onChange(true);
        else props.onChange(false);
      }}
      aria-label={fieldLabel ?? undefined}
    >
      <option value="">— не выбрано —</option>
      <option value="true">да</option>
      <option value="false">нет</option>
    </select>
  );
}

export function CheckboxInput(props: {
  value: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  const fieldLabel = useFieldLabel();
  return (
    /* A4 (MVP-8.2, раунд 2): Chromium ignores padding on a native checkbox,
       so box-content+p-2 gave 16x16; the wrapping label is the 32x32 target
       (clicking it toggles the control) while the box stays 16x16 visually.
       Раунд 3 (B4): inline-flex без justify-center — инлайн-обёртка тянется
       только на чекбокс и оставляет его слева, как в раунде 1. */
    <label className="inline-flex min-h-8 min-w-8 cursor-pointer items-center">
      <input
        type="checkbox"
        className="h-4 w-4 accent-accent-bright"
        checked={props.value}
        disabled={props.disabled}
        aria-label={fieldLabel ?? undefined}
        onChange={(e) => props.onChange(e.target.checked)}
      />
    </label>
  );
}

export function Section(props: { title: string; children: ReactNode; className?: string }) {
  return (
    <section
      className={
        "rounded-card border border-zinc-800 bg-surface/60 p-4 shadow-card sm:p-5 " + (props.className ?? "")
      }
    >
      <h2 className="mb-3 text-base font-semibold tracking-tight text-text">{props.title}</h2>
      <div className="space-y-3">{props.children}</div>
    </section>
  );
}

/** Широкие таблицы прокручиваются внутри контейнера, а не всей страницей (R11). */
export function TableWrap(props: { children: ReactNode; label?: string }) {
  return (
    <div
      className="-mx-1 overflow-x-auto px-1"
      role={props.label ? "region" : undefined}
      aria-label={props.label}
      tabIndex={props.label ? 0 : undefined}
    >
      {props.children}
    </div>
  );
}

export function ErrorBanner(props: { text: string | null }) {
  if (!props.text) return null;
  return (
    <div role="alert" className="rounded-control border border-red-800/80 bg-red-950/40 px-3 py-2 text-sm text-red-300">
      {props.text}
    </div>
  );
}

export function SuccessBanner(props: { text: string | null }) {
  if (!props.text) return null;
  return (
    <div role="status" className="rounded-control border border-emerald-800/80 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-300">
      {props.text}
    </div>
  );
}

export function Loading(props: { text?: string }) {
  return <p className="text-sm text-text-muted">{props.text ?? "Загрузка…"}</p>;
}

export function Button(props: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "danger" | "ghost";
  title?: string;
}) {
  const variantClass =
    props.variant === "danger"
      ? "border-red-800 bg-red-950/40 text-red-300 hover:bg-red-900/40"
      : props.variant === "ghost"
        ? "border-zinc-700 text-text-secondary hover:border-zinc-600 hover:bg-zinc-800 hover:text-text"
        : "border-accent-bright/20 bg-accent text-white shadow-[0_6px_18px_-8px_rgb(79_70_229/0.9)] hover:bg-accent-strong";
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      title={props.title}
      className={
        "min-h-9 rounded-control border px-3.5 py-1.5 text-sm font-medium transition-[background-color,border-color,color,transform] duration-(--duration-fast) active:translate-y-px disabled:cursor-not-allowed disabled:opacity-40 " +
        variantClass
      }
    >
      {props.children}
    </button>
  );
}
