import { useEffect, useMemo, useRef, useState } from "react";

export interface PeriodRange {
  from: Date | null;
  to: Date | null;
}

interface PeriodPickerProps {
  from: Date | null;
  to: Date | null;
  onChange: (from: Date | null, to: Date | null) => void;
  /** Earliest date with data, "YYYY-MM-DD" (local), or null when unknown. */
  earliestAvailable?: string | null;
}

const MONTHS_RU = [
  "январь",
  "февраль",
  "март",
  "апрель",
  "май",
  "июнь",
  "июль",
  "август",
  "сентябрь",
  "октябрь",
  "ноябрь",
  "декабрь",
];
const WEEKDAYS_RU = ["П", "В", "С", "Ч", "П", "С", "В"];

interface Preset {
  key: string;
  label: string;
  monthsBack?: number;
  daysBack?: number;
}

const PRESETS: Preset[] = [
  { key: "month", label: "Месяц", monthsBack: 1 },
  { key: "3m", label: "3 месяца", monthsBack: 3 },
  { key: "6m", label: "6 месяцев", monthsBack: 6 },
  { key: "year", label: "Год", daysBack: 365 },
  { key: "3y", label: "3 года", daysBack: 1095 },
  { key: "all", label: "Весь период" },
];

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** 17.03.26 7:21 — compact form shown in the field summary. */
function formatShort(d: Date): string {
  return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.${pad2(d.getFullYear() % 100)} ${d.getHours()}:${pad2(d.getMinutes())}`;
}

/** 17.03.26 — compact form shown next to presets. */
function formatDayShort(d: Date): string {
  return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.${pad2(d.getFullYear() % 100)}`;
}

/** 17.03.2026 — the manual date input form. */
function formatDateInput(d: Date | null): string {
  return d ? `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.${d.getFullYear()}` : "";
}

/** 07:21 — the manual time input form. */
function formatTimeInput(d: Date | null): string {
  return d ? `${pad2(d.getHours())}:${pad2(d.getMinutes())}` : "";
}

function parseDateInput(s: string): Date | null {
  const m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(s.trim());
  if (!m) return null;
  const day = Number(m[1]);
  const month = Number(m[2]);
  const year = Number(m[3]);
  const d = new Date(year, month - 1, day);
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) return null;
  return d;
}

function parseTimeInput(s: string): { h: number; m: number } | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(s.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return null;
  return { h, m: min };
}

/** Shift by whole calendar months, preserving the time-of-day. */
function addMonths(d: Date, delta: number): Date {
  const res = new Date(d);
  const day = d.getDate();
  res.setDate(1);
  res.setMonth(res.getMonth() + delta);
  const maxDay = new Date(res.getFullYear(), res.getMonth() + 1, 0).getDate();
  res.setDate(Math.min(day, maxDay));
  return res;
}

function dateOnly(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function parseEarliest(s: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  if (d.getFullYear() !== Number(m[1]) || d.getMonth() !== Number(m[2]) - 1 || d.getDate() !== Number(m[3])) {
    return null;
  }
  return d;
}

function applyTime(base: Date | null, h: number, min: number): Date {
  const d = base ? new Date(base) : new Date();
  d.setHours(h, min, 0, 0);
  return d;
}

/**
 * U11 (MVP-7.5): the «Период» field of the backtest form — one field with a
 * readable range value, a calendar popup with range selection and a quick
 * presets dropdown. The component is self-contained (no calendar library):
 * the project has no heavy UI dependencies yet.
 */
export function PeriodPicker(props: PeriodPickerProps) {
  const { from, to, onChange, earliestAvailable } = props;
  const [open, setOpen] = useState(false);
  const [presetsOpen, setPresetsOpen] = useState(false);

  const earliest = useMemo(() => (earliestAvailable ? parseEarliest(earliestAvailable) : null), [earliestAvailable]);
  const today = dateOnly(new Date());

  const anchor = to ?? from ?? new Date();
  const [viewYear, setViewYear] = useState(anchor.getFullYear());
  const [viewMonth, setViewMonth] = useState(anchor.getMonth());

  // Manual date/time row drafts: typed values keep their partial state while
  // the parseable pair is committed to the picker's value.
  const [drafts, setDrafts] = useState({
    fromDate: formatDateInput(from),
    fromTime: formatTimeInput(from),
    toDate: formatDateInput(to),
    toTime: formatTimeInput(to),
  });

  useEffect(() => {
    setDrafts({
      fromDate: formatDateInput(from),
      fromTime: formatTimeInput(from),
      toDate: formatDateInput(to),
      toTime: formatTimeInput(to),
    });
  }, [from, to]);

  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setPresetsOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const summary = from && to ? `${formatShort(from)} - ${formatShort(to)}` : "";

  const cells = useMemo(() => {
    const first = new Date(viewYear, viewMonth, 1);
    const lead = (first.getDay() + 6) % 7; // Monday-first
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const out: (Date | null)[] = [];
    for (let i = 0; i < lead; i++) out.push(null);
    for (let d = 1; d <= daysInMonth; d++) out.push(new Date(viewYear, viewMonth, d));
    return out;
  }, [viewYear, viewMonth]);

  const isDisabled = (d: Date) => {
    const dd = dateOnly(d);
    if (dd.getTime() > today.getTime()) return true;
    if (earliest && dd.getTime() < earliest.getTime()) return true;
    return false;
  };

  const pickDay = (d: Date) => {
    if (isDisabled(d)) return;
    if (!from || (from && to)) {
      onChange(d, null);
    } else if (d.getTime() >= from.getTime()) {
      onChange(from, d);
    } else {
      onChange(d, null);
    }
  };

  const applyPreset = (p: Preset) => {
    const now = new Date();
    if (p.key === "all") {
      if (!earliest) return;
      onChange(earliest, now);
    } else if (p.monthsBack !== undefined) {
      onChange(addMonths(now, -p.monthsBack), now);
    } else {
      onChange(new Date(now.getTime() - (p.daysBack ?? 0) * 86_400_000), now);
    }
    setPresetsOpen(false);
  };

  const presetRange = (p: Preset): string => {
    const now = new Date();
    if (p.key === "all") return "—";
    const start =
      p.monthsBack !== undefined
        ? addMonths(now, -p.monthsBack)
        : new Date(now.getTime() - (p.daysBack ?? 0) * 86_400_000);
    return `${formatDayShort(start)}-${formatDayShort(now)}`;
  };

  const visiblePresets = PRESETS.filter((p) => {
    if (p.key === "all") return true;
    if (!earliest) return true;
    const now = new Date();
    const start = p.monthsBack !== undefined ? addMonths(now, -p.monthsBack) : new Date(now.getTime() - (p.daysBack ?? 0) * 86_400_000);
    return dateOnly(start).getTime() >= earliest.getTime();
  });

  const setDraft = (edge: "from" | "to", part: "date" | "time", value: string) => {
    const key = edge + (part === "date" ? "Date" : "Time");
    const next = { ...drafts, [key]: value };
    setDrafts(next);
    const date = parseDateInput(next[`${edge}Date`]);
    const time = parseTimeInput(next[`${edge}Time`]);
    if (date && time) {
      const nd = applyTime(date, time.h, time.m);
      onChange(edge === "from" ? nd : from, edge === "from" ? to : nd);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false);
      setPresetsOpen(false);
    }
  };

  const shiftMonth = (delta: number) => {
    const d = new Date(viewYear, viewMonth + delta, 1);
    setViewYear(d.getFullYear());
    setViewMonth(d.getMonth());
  };

  const between = (d: Date) => {
    if (!from || !to) return false;
    const dd = dateOnly(d).getTime();
    const a = dateOnly(from).getTime();
    const b = dateOnly(to).getTime();
    return dd > Math.min(a, b) && dd < Math.max(a, b);
  };

  const isEdge = (d: Date, which: "from" | "to") => {
    const v = which === "from" ? from : to;
    return !!v && dateOnly(d).getTime() === dateOnly(v).getTime();
  };

  const dayClass = (d: Date) => {
    if (isDisabled(d)) return "text-zinc-600";
    const cls = ["text-zinc-200 hover:bg-zinc-700"];
    if (isEdge(d, "from")) cls.push("bg-sky-600 font-semibold text-white hover:bg-sky-600");
    else if (isEdge(d, "to")) cls.push("bg-sky-500 text-white hover:bg-sky-500");
    else if (between(d)) cls.push("bg-sky-900/60 text-sky-100");
    return cls.join(" ");
  };

  return (
    <div ref={rootRef} className="relative">
      <div className="flex">
        <input
          type="text"
          readOnly
          className="w-full rounded-l border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-200"
          value={summary}
          placeholder="выберите период"
          onClick={() => {
            setOpen((v) => !v);
            setPresetsOpen(false);
          }}
          onKeyDown={onKeyDown}
          aria-label="Период"
        />
        <button
          type="button"
          className="rounded-r border border-l-0 border-zinc-700 bg-zinc-900 px-2 text-zinc-400 hover:text-zinc-200"
          onClick={() => {
            setOpen((v) => !v);
            setPresetsOpen(false);
          }}
          aria-label="Открыть календарь"
        >
          📅
        </button>
      </div>

      {open ? (
        <div
          className="absolute left-0 top-full z-20 mt-1 w-[320px] rounded-lg border border-zinc-700 bg-zinc-900 p-3 shadow-xl"
          role="dialog"
          aria-label="Выбор периода"
          onKeyDown={onKeyDown}
        >
          <div className="mb-2 flex items-center justify-between">
            <button
              type="button"
              className="px-2 text-zinc-400 hover:text-zinc-200"
              onClick={() => shiftMonth(-1)}
              aria-label="Предыдущий месяц"
            >
              ←
            </button>
            <span className="text-sm font-medium capitalize text-zinc-100">
              {MONTHS_RU[viewMonth]} {viewYear}
            </span>
            <button
              type="button"
              className="px-2 text-zinc-400 hover:text-zinc-200"
              onClick={() => shiftMonth(1)}
              aria-label="Следующий месяц"
            >
              →
            </button>
          </div>

          <div className="grid grid-cols-7 gap-1 text-center text-xs">
            {WEEKDAYS_RU.map((w, i) => (
              <div key={`${w}${i}`} className="py-1 text-zinc-500">
                {w}
              </div>
            ))}
            {cells.map((d, i) =>
              d ? (
                <button
                  type="button"
                  key={d.toISOString()}
                  disabled={isDisabled(d)}
                  onClick={() => pickDay(d)}
                  className={dayClass(d)}
                  aria-label={`${d.getDate()}.${d.getMonth() + 1}.${d.getFullYear()}`}
                >
                  {d.getDate()}
                </button>
              ) : (
                <div key={`blank-${i}`} />
              ),
            )}
          </div>

          <div className="mt-3 space-y-2 border-t border-zinc-800 pt-2">
            <div className="flex items-center gap-2 text-xs">
              <span className="w-10 text-zinc-500">С</span>
              <span aria-hidden>📅</span>
              <input
                type="text"
                className="w-24 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"
                value={drafts.fromDate}
                placeholder="ДД.ММ.ГГГГ"
                onChange={(e) => setDraft("from", "date", e.target.value)}
                aria-label="Дата начала"
              />
              <span aria-hidden>🕐</span>
              <input
                type="text"
                className="w-16 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"
                value={drafts.fromTime}
                placeholder="ЧЧ:ММ"
                onChange={(e) => setDraft("from", "time", e.target.value)}
                aria-label="Время начала"
              />
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="w-10 text-zinc-500">По</span>
              <span aria-hidden>📅</span>
              <input
                type="text"
                className="w-24 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"
                value={drafts.toDate}
                placeholder="ДД.ММ.ГГГГ"
                onChange={(e) => setDraft("to", "date", e.target.value)}
                aria-label="Дата конца"
              />
              <span aria-hidden>🕐</span>
              <input
                type="text"
                className="w-16 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"
                value={drafts.toTime}
                placeholder="ЧЧ:ММ"
                onChange={(e) => setDraft("to", "time", e.target.value)}
                aria-label="Время конца"
              />
            </div>
          </div>

          <div className="relative mt-3">
            <button
              type="button"
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-left text-xs text-zinc-300"
              onClick={() => setPresetsOpen((v) => !v)}
            >
              Быстрый выбор ▾
            </button>
            {presetsOpen ? (
              <div className="absolute left-0 top-full z-30 mt-1 w-full rounded border border-zinc-700 bg-zinc-900 shadow-xl">
                {visiblePresets.map((p) => {
                  if (p.key === "all" && !earliest) {
                    return (
                      <button
                        type="button"
                        key={p.key}
                        disabled
                        title="нет данных о доступном диапазоне"
                        className="w-full px-3 py-1.5 text-left text-xs text-zinc-600"
                      >
                        <span className="flex items-center justify-between">
                          <span>Весь период</span>
                          <span className="pl-3">нет данных о доступном диапазоне</span>
                        </span>
                      </button>
                    );
                  }
                  return (
                    <button
                      type="button"
                      key={p.key}
                      onClick={() => applyPreset(p)}
                      className="w-full px-3 py-1.5 text-left text-xs text-zinc-200 hover:bg-zinc-800"
                    >
                      <span className="flex items-center justify-between">
                        <span>{p.label}</span>
                        <span className="pl-3 text-zinc-500">{presetRange(p)}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>

          <p className="mt-3 border-t border-zinc-800 pt-2 text-xs text-zinc-500">
            {earliest
              ? `Данные для бэктеста доступны с: ${pad2(earliest.getDate())}.${pad2(earliest.getMonth() + 1)}.${earliest.getFullYear()}`
              : "нет данных о доступном диапазоне"}
          </p>
        </div>
      ) : null}
    </div>
  );
}
