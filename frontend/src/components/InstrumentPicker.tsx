import { useMemo, useState } from "react";
import type { KeyboardEvent } from "react";
import type { InstrumentInfo } from "../types";
import { filterInstruments } from "../lib/instrumentSearch";

/** U3 label without the "(type / currency)" suffix. */
export function instrumentLabel(inst: InstrumentInfo | null | undefined): string {
  return inst ? `${inst.ticker} — ${inst.name ?? ""}` : "";
}

/**
 * U2/U9 live-search instrument picker (shared by «Обзор» and the strategy
 * form): a combobox over already-loaded instruments with a dropdown list,
 * «Найдено: N из M» counter and keyboard navigation.
 *
 * M1/M2 (MVP-7.4 review): while the list is closed the field shows the label
 * of the selected paper (never the raw id / nothing), and focusing the field
 * shows the full list again — the query is reset on focus instead of being
 * left as the long selected label.
 */
export function InstrumentPicker(props: {
  instruments: InstrumentInfo[];
  /** FIGI of the selected instrument ("" = none). */
  selectedFigi: string;
  onSelect: (figi: string) => void;
  placeholder?: string;
  /** Shown when selectedFigi is not found in the list (e.g. stale id). */
  fallbackLabel?: string;
  listId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);

  const selected = props.instruments.find((i) => i.figi === props.selectedFigi);
  const label = selected ? instrumentLabel(selected) : (props.fallbackLabel ?? "");
  const filtered = useMemo(
    () => filterInstruments(query, props.instruments),
    [query, props.instruments],
  );

  const pick = (figi: string) => {
    props.onSelect(figi);
    setOpen(false);
    setQuery("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) {
        // Re-open with the full list (M1), like focus does.
        setOpen(true);
        setQuery("");
        setHighlight(0);
        return;
      }
      setHighlight((h) => Math.min(h + 1, Math.max(filtered.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const pickItem = filtered[highlight];
      if (open && pickItem) pick(pickItem.figi);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  const listId = props.listId ?? "instrument-picker-results";

  return (
    <div className="relative">
      <input
        className="w-full rounded border border-zinc-700 bg-zinc-900 p-2 text-sm"
        placeholder={props.placeholder ?? "Поиск по тикеру, названию или FIGI…"}
        value={open ? query : label}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setHighlight(0);
        }}
        onFocus={() => {
          setOpen(true);
          setQuery("");
          setHighlight(0);
        }}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      {open ? (
        <div
          id={listId}
          className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded border border-zinc-700 bg-zinc-900"
        >
          <p className="px-3 py-1 text-xs text-zinc-500">
            Найдено: {filtered.length} из {props.instruments.length}
          </p>
          {filtered.length === 0 ? (
            <p className="px-3 py-2 text-sm text-zinc-500">Ничего не найдено</p>
          ) : (
            <ul>
              {filtered.map((inst, idx) => (
                <li key={inst.figi}>
                  <button
                    type="button"
                    className={`block w-full px-3 py-1.5 text-left text-sm ${
                      idx === highlight ? "bg-zinc-800" : ""
                    } ${inst.figi === props.selectedFigi ? "text-emerald-400" : ""}`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      pick(inst.figi);
                    }}
                  >
                    {instrumentLabel(inst)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
