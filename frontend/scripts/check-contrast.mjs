#!/usr/bin/env node
/**
 * MVP-8.3, раунд 2 (T1/T8): статическая проверка WCAG 2.1 AA контраста
 * в ОБЕИХ темах («Тёмная» и «Светлая»):
 *   - text/background пары >= 4.5:1 (WCAG 1.4.3), как в MVP-8.2;
 *   - границы интерактивных элементов и фокус-рамки >= 3:1 (WCAG 1.4.11) —
 *     только для токенов border и accent-bright (декоративные линии таблиц,
 *     рамки баннеров и hover-подсветки в гейт не входят: элемент опознаётся
 *     заливкой и текстом >= 4.5:1).
 *
 * Скрипт извлекает классы `text-*` / `bg-*` из всех файлов src (.tsx/.css),
 * приводит каждый утилитный класс к HEX из палитры кадой темы (zinc/sky/red/
 * amber/emerald + токены @theme и переопределения :root[data-theme="light"])
 * и вычисляет контраст по формуле WCAG (relative luminance).
 *
 * Ограничения (осознанные):
 * - полупрозрачные фоны (bg-zinc-900/40 и т.п.) считаются наложением на
 *   страницу текущей темы — наихудший случай;
 * - `text-zinc-600` и `text-muted/50` исключаются: в коде это состояния
 *   disabled (WCAG 1.4.3 не применяется к неактивному тексту);
 * - условные классы, собираемые конкатенацией через `${...}`, проверяются
 *   по статическим фрагментам строк; пары, которые склейка прячет (кнопки,
 *   календарь, заглушки), — в списке EXTRA_PAIRS ниже.
 *
 * Запуск: npm run check:contrast
 */
import { readFileSync } from "node:fs";
import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const CSS = readFileSync("src/index.css", "utf8");

// --- Токены: базовый блок @theme и переопределения светлой темы ------------

function extractColors(text) {
  const map = new Map();
  for (const m of text.matchAll(/--color-([a-z0-9-]+):\s*([^;]+);/g)) map.set(m[1], m[2].trim());
  return map;
}

const baseRaw = new Map();
for (const block of CSS.matchAll(/@theme\s*\{([\s\S]*?)\n\}/g)) {
  for (const [name, value] of extractColors(block[1])) baseRaw.set(name, value);
}

const lightBlock = CSS.match(/:root\[data-theme="light"\]\s*\{([\s\S]*?)\n\}/);
const lightRaw = new Map(baseRaw);
if (lightBlock) {
  for (const [name, value] of extractColors(lightBlock[1])) lightRaw.set(name, value);
}

function resolveAll(raw) {
  const resolveVar = (name, depth = 0) => {
    const v = raw.get(name);
    if (v === undefined || depth > 5) return undefined;
    const ref = /^var\(--color-([a-z0-9-]+)\)$/.exec(v);
    return ref ? resolveVar(ref[1], depth + 1) : v;
  };
  const out = new Map();
  for (const name of raw.keys()) out.set(name, resolveVar(name));
  return out;
}

const BASE = resolveAll(baseRaw);
const LIGHT = resolveAll(lightRaw);

// Стандартные палитры Tailwind 4 (не зависят от темы).
const STATIC = {
  sky: {
    50: "#f0f9ff", 100: "#e0f2fe", 200: "#bae6fd", 300: "#7dd3fc",
    400: "#38bdf8", 500: "#0ea5e9", 600: "#0284c7", 700: "#0369a1",
    800: "#075985", 900: "#0c4a6e", 950: "#082f49",
  },
  red: {
    50: "#fef2f2", 100: "#fee2e2", 200: "#fecaca", 300: "#fca5a5",
    400: "#f87171", 500: "#ef4444", 600: "#dc2626", 700: "#b91c1c",
    800: "#991b1b", 900: "#7f1d1d", 950: "#450a0a",
  },
  amber: {
    50: "#fffbeb", 100: "#fef3c7", 200: "#fde68a", 300: "#fcd34d",
    400: "#fbbf24", 500: "#f59e0b", 600: "#d97706", 700: "#b45309",
    800: "#92400e", 900: "#78350f", 950: "#451a03",
  },
  emerald: {
    50: "#ecfdf5", 100: "#d1fae5", 200: "#a7f3d0", 300: "#6ee7b7",
    400: "#34d399", 500: "#10b981", 600: "#059669", 700: "#047857",
    800: "#065f46", 900: "#064e3b", 950: "#022c22",
  },
};

function paletteFor(tokens) {
  return {
    zinc: Object.fromEntries(
      [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950].map((n) => [n, tokens.get(`zinc-${n}`)]),
    ),
    ...STATIC,
    // Семантические токены @theme без числового суффикса (page, surface,
    // accent-bright, error-soft, …). Значения-функции (color-mix, rgb, var
    // без zinc-базы) в гейт не входят — это декоративные линии и оверлеи.
    tokens: Object.fromEntries(
      [...tokens.entries()].filter(
        ([k, v]) => !/^(zinc|sky|red|amber|emerald)-\d+$/.test(k) && /^#[0-9a-f]{6}$/i.test(v ?? ""),
      ),
    ),
  };
}

const THEME_KEYS = ["dark", "light"];
const THEMES = {
  dark: { palette: paletteFor(BASE), page: BASE.get("page") },
  light: { palette: paletteFor(LIGHT), page: LIGHT.get("page") },
};

// --- WCAG-математика --------------------------------------------------------

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
}

function relLuminance(hex) {
  const [r, g, b] = hexToRgb(hex).map((c) =>
    c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const la = relLuminance(a);
  const lb = relLuminance(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

/** Наложение полупрозрачного фона поверх страницы темы (наихудший случай). */
function blend(fg, alpha, page) {
  const [fr, fg2, fb] = hexToRgb(fg);
  const [pr, pg, pb] = hexToRgb(page);
  const mix = (f, p) => Math.round((f * alpha + p * (1 - alpha)) * 255);
  const toHex = (n) => n.toString(16).padStart(2, "0");
  return `#${toHex(mix(fr, pr))}${toHex(mix(fg2, pg))}${toHex(mix(fb, pb))}`;
}

function resolve(name, themeKey) {
  // name: "zinc-400", "zinc-900/40", "text-muted", "error-soft/70", "white", …
  if (name === "white") return { hex: "#ffffff", alpha: 1 };
  if (name === "black") return { hex: "#000000", alpha: 1 };
  const pal = THEMES[themeKey].palette;
  const slash = /^(.*)\/(\d{1,3})$/.exec(name);
  const base = slash ? slash[1] : name;
  const alpha = slash ? Number(slash[2]) / 100 : 1;
  if (pal.tokens[base]) return { hex: pal.tokens[base], alpha };
  const m = /^([a-z]+)-(\d{1,3})$/.exec(base);
  if (m && pal[m[1]]) {
    const hex = pal[m[1]][Number(m[2])];
    if (!hex) return null;
    return { hex, alpha };
  }
  return null;
}

/** Итоговая гекс-заливка пары (учёт alpha поверх страницы темы). */
function bgHexFor(name, themeKey) {
  const b = resolve(name, themeKey);
  if (!b?.hex) return undefined;
  return b.alpha < 1 ? blend(b.hex, b.alpha, THEMES[themeKey].page) : b.hex;
}

// --- Сбор пар из разметки ---------------------------------------------------

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/(\.tsx|\.css)$/.test(entry)) out.push(p);
  }
  return out;
}

const CLASS_RE = /\b(?:className|class)\s*=\s*["'`]([^"'`]*)["'`]/g;

const TOKEN_TEXT = "(zinc-\\d{2,3}(?:\\/\\d+)?|red-\\d{2,3}(?:\\/\\d+)?|amber-\\d{2,3}(?:\\/\\d+)?|emerald-\\d{2,3}(?:\\/\\d+)?|sky-\\d{2,3}(?:\\/\\d+)?|white|black|text-secondary|text-muted(?:\\/\\d+)?|text|accent-bright|accent-strong|accent-soft|accent|error|warning|success)(?![\\w-])";
const TOKEN_BG = "(zinc-\\d{2,3}(?:\\/\\d+)?|red-\\d{2,3}(?:\\/\\d+)?|amber-\\d{2,3}(?:\\/\\d+)?|emerald-\\d{2,3}(?:\\/\\d+)?|sky-\\d{2,3}(?:\\/\\d+)?|page(?:\\/\\d+)?|surface(?:\\/\\d+)?|surface-raised|accent-strong|accent-soft|accent(?:\\/\\d+)?|error-soft(?:\\/\\d+)?|error|warning-soft(?:\\/\\d+)?|warning(?:\\/\\d+)?|success-soft(?:\\/\\d+)?|success|control(?:\\/\\d+)?|sunken(?:\\/\\d+)?)(?![\\w-])";

const MIN_RATIO = 4.5;
// Только состояния disabled (WCAG 1.4.3 не распространяется на disabled).
const EXCLUDED_TEXT = new Set(["zinc-600", "text-muted/50"]);

const pairs = new Map(); // key `${text} | ${bg}` -> {text, bg, files}

for (const file of walk("src")) {
  const content = readFileSync(file, "utf8");
  for (const m of content.matchAll(CLASS_RE)) {
    const classStr = m[1];
    // Динамические вставки ${...} не разбираем; пропускаем такие строки.
    if (classStr.includes("${") || classStr.includes("}")) continue;

    const textTokens = [...classStr.matchAll(new RegExp(`\\btext-${TOKEN_TEXT}`, "g"))].map((x) => x[1]);
    if (textTokens.length === 0) continue;
    const bgTokens = [...classStr.matchAll(new RegExp(`\\bbg-${TOKEN_BG}`, "g"))].map((x) => x[1]);
    const text = textTokens[textTokens.length - 1];
    const bgName = bgTokens.length > 0 ? bgTokens[bgTokens.length - 1] : "page";

    const plain = text.replace(/^text-/, "");
    if (EXCLUDED_TEXT.has(plain)) continue;

    const key = `${text} on bg-${bgName}`;
    if (!pairs.has(key)) pairs.set(key, { text, bg: bgName, files: [] });
    pairs.get(key).files.push(relative("src", file));
  }
}

// Пары из условных/шаблонных классов (склеиваются конкатенацией строк —
// кнопки FormControls, режим ModeBadge, календарь PeriodPicker) — держим их
// здесь как явные инварианты обеих тем. Значения вида /NN — alpha-заливка.
const EXTRA_PAIRS = [
  ["white", "accent"], // основная кнопка (Button primary)
  ["white", "accent-strong"], // край диапазона календаря; hover основной кнопки
  ["text", "accent-soft"], // календарь: текст внутри диапазона
  ["text", "accent-soft/70"], // дни диапазона PeriodPicker (склейка dayClass)
  ["accent-bright", "page"], // акцентный текст (вордмарк, легенда графика)
  ["accent-bright", "surface"],
  ["accent-bright", "surface-raised"],
  ["success", "page"], // PnL > 0, дот статуса
  ["success", "surface"],
  ["error", "page"], // PnL < 0, ошибки
  ["error", "surface"],
  ["error", "error-soft"], // баннеры и бейдж «Реальные деньги»
  ["error", "error-soft/70"],
  ["warning", "surface"],
  ["warning", "warning-soft"],
  ["warning", "warning-soft/70"],
  ["success", "success-soft"],
  ["success", "success-soft/70"],
  ["text-secondary", "surface"], // вторичный текст, подписи полей
  ["text-secondary", "page"], // ghost-кнопка (кнопка на странице)
  ["text-muted", "surface-raised"], // приглушённый текст на активной вкладке
  ["text", "surface-raised"],
  ["text", "control/70"], // поля ввода FormControls (bg-control/70)
  ["text", "sunken"], // textarea/редактор JSON, поле периода
  ["text-muted", "sunken"], // подпись «нет данных» в тёмных панелях
];

for (const [text, bgName] of EXTRA_PAIRS) {
  const key = `${text} on bg-${bgName}`;
  if (!pairs.has(key)) pairs.set(key, { text, bg: bgName, files: [] });
  pairs.get(key).files.push("EXTRA_PAIRS");
}

// B3 (раунд 1) + раунд 2: ::placeholder глобально стилизован токеном
// text-muted; поля ввода теперь на control/70 (FormControls) и sunken
// (PeriodPicker) — проверяем пару на этих заливках в обеих темах.
const PLACEHOLDER_BGS = [
  ["text-muted", "control/70"],
  ["text-muted", "sunken"],
];

for (const [text, bgName] of PLACEHOLDER_BGS) {
  const key = `placeholder ${text} on bg-${bgName}`;
  pairs.set(key, { text, bg: bgName, files: ["index.css ::placeholder"] });
}

// --- WCAG 1.4.11: границы и фокус-рамки (не текст) --------------------------

// border — рамка интерактивных элементов (поля, кнопки, бургер, сегменты
// переключателя); accent-bright — глобальная фокус-рамка (:focus-visible).
const UI_BOUNDARY = [
  ["border", "page"],
  ["border", "surface"],
  ["border", "surface-raised"],
  ["border", "control"],
  ["border", "sunken"],
  ["accent-bright", "page"],
  ["accent-bright", "surface"],
  ["accent-bright", "surface-raised"],
  ["accent-bright", "control/70"],
  ["accent-bright", "sunken"],
];
const MIN_BOUNDARY_RATIO = 3.0;

// --- Вывод ------------------------------------------------------------------

let failed = 0;
for (const themeKey of THEME_KEYS) {
  const label = themeKey === "dark" ? "ТЁМНАЯ" : "СВЕТЛАЯ";
  console.log(`\n=== Тема: ${label} ===`);

  const rows = [...pairs.values()]
    .map((p) => {
      const t = resolve(p.text, themeKey);
      const bgHex = bgHexFor(p.bg, themeKey);
      if (!t?.hex || !bgHex) return null;
      return {
        ...p,
        ratio: Math.round(contrast(t.hex, bgHex) * 100) / 100,
        group: "text",
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.ratio - b.ratio);

  for (const p of rows) {
    const ok = p.ratio >= MIN_RATIO;
    if (!ok) failed++;
    console.log(
      `${ok ? "OK  " : "FAIL"} ${String(p.ratio).padStart(5)}:1  text-${p.text.padStart(16)} on bg-${p.bg}  (${p.files[0]})`,
    );
  }
  console.log(`\n${rows.length} text/bg пар, ${rows.filter((r) => r.ratio < MIN_RATIO).length} ниже ${MIN_RATIO}:1`);

  console.log(`\n--- 1.4.11 (границы/фокус, >= ${MIN_BOUNDARY_RATIO}:1) ---`);
  for (const [boundary, surface] of UI_BOUNDARY) {
    const b = bgHexFor(boundary, themeKey);
    const s = bgHexFor(surface, themeKey);
    if (!b || !s) {
      console.log(`SKIP ${boundary} vs ${surface} — не токен гейта`);
      continue;
    }
    const ratio = Math.round(contrast(b, s) * 100) / 100;
    const ok = ratio >= MIN_BOUNDARY_RATIO;
    if (!ok) failed++;
    console.log(`${ok ? "OK  " : "FAIL"} ${String(ratio).padStart(5)}:1  ${boundary} vs ${surface}`);
  }
}

console.log(`\n========== ИТОГ: ${failed} нарушений ==========`);
process.exit(failed > 0 ? 1 : 0);
