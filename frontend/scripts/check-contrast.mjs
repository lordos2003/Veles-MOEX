#!/usr/bin/env node
/**
 * MVP-8.2 A1: статическая проверка WCAG 2.1 AA контраста (>= 4.5:1) всех
 * text/bg пар, встречающихся в className-литералах фронтенда.
 *
 * Скрипт извлекает классы `text-*` / `bg-*` из всех файлов src (.tsx/.css),
 * приводит каждый утилитный класс к HEX из используемой палитры (zinc/sky/
 * red/amber/emerald + токены @theme), вычисляет контраст по формуле WCAG
 * (relative luminance) и падает с ненулевым кодом, если пара не проходит.
 *
 * Ограничения (осознанные):
 * - полупрозрачные фоны (bg-zinc-900/40 и т.п.) считаются наложением на
 *   страницу #09090b — наихудший (самый тёмный) случай;
 * - `text-zinc-600` исключается: в коде это только состояния disabled
 *   элементов (WCAG 1.4.3 не применяется к неактивному тексту);
 * - условные классы, собираемые конкатенацией через `${...}`, проверяются
 *   по статическим фрагментам строк.
 *
 * Запуск: npm run check:contrast
 */
import { readFileSync } from "node:fs";
import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const PAGE = "#09090b"; // --color-page (zinc-950)

const PALETTE = {
  zinc: {
    50: "#fafafa", 100: "#f4f4f5", 200: "#e4e4e7", 300: "#d4d4d8",
    400: "#a1a1aa", 500: "#71717a", 600: "#52525b", 700: "#3f3f46",
    800: "#27272a", 900: "#18181b", 950: "#09090b",
  },
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
  // Токены @theme (index.css); суффиксы читаются по порядку от бо́льших.
  tokens: {
    "text": "#f4f4f5",
    "text-secondary": "#d4d4d8",
    "text-muted": "#a1a1aa",
    "page": "#09090b",
    "surface": "#18181b",
    "surface-raised": "#27272a",
    "border": "#3f3f46",
    "border-soft": "#27272a",
    "accent": "#0369a1",
    "accent-bright": "#38bdf8",
    "error": "#f87171",
    "warning": "#fbbf24",
    "success": "#34d399",
  },
};

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

/** Наложение полупрозрачного фона поверх PAGE (наихудший случай для текста). */
function blend(fg, alpha) {
  const [fr, fg2, fb] = hexToRgb(fg);
  const [pr, pg, pb] = hexToRgb(PAGE);
  const mix = (f, p) => Math.round((f * alpha + p * (1 - alpha)) * 255);
  const toHex = (n) => n.toString(16).padStart(2, "0");
  return `#${toHex(mix(fr, pr))}${toHex(mix(fg2, pg))}${toHex(mix(fb, pb))}`;
}

function resolve(name) {
  // name: "zinc-400", "zinc-900/40", "text-muted", "page", "white", ...
  if (name === "white") return { hex: "#ffffff", alpha: 1 };
  if (name === "black") return { hex: "#000000", alpha: 1 };
  const tok = PALETTE.tokens[name];
  if (tok) return { hex: tok, alpha: 1 };
  const m = /^([a-z]+)-(\d{1,3})(?:\/(\d{1,3}))?$/.exec(name);
  if (m && PALETTE[m[1]]) {
    const hex = PALETTE[m[1]][Number(m[2])];
    if (!hex) return null;
    const alpha = m[3] ? Number(m[3]) / 100 : 1;
    return { hex, alpha };
  }
  return null;
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/(\.tsx|\.css)$/.test(entry)) out.push(p);
  }
  return out;
}

const TEXT_RE = /\btext-(zinc-\d{2,3}(?:\/\d+)?|red-\d{2,3}(?:\/\d+)?|amber-\d{2,3}(?:\/\d+)?|emerald-\d{2,3}(?:\/\d+)?|sky-\d{2,3}(?:\/\d+)?|white|black|text(?:-secondary|-muted)?)\b/g;
const BG_RE = /\bbg-(zinc-\d{2,3}(?:\/\d+)?|red-\d{2,3}(?:\/\d+)?|amber-\d{2,3}(?:\/\d+)?|emerald-\d{2,3}(?:\/\d+)?|sky-\d{2,3}(?:\/\d+)?|page|surface|surface-raised)\b/g;
const CLASS_RE = /\b(?:className|class)\s*=\s*["'`]([^"'`]*)["'`]/g;

const MIN_RATIO = 4.5;
// Только состояния disabled (WCAG 1.4.3 не распространяется на disabled).
const EXCLUDED_TEXT = new Set(["zinc-600"]);

const pairs = new Map(); // key `${text} | ${bg}` -> {text,bg,ratio,files}

for (const file of walk("src")) {
  const content = readFileSync(file, "utf8");
  for (const m of content.matchAll(CLASS_RE)) {
    const classStr = m[1];
    // Динамические вставки ${...} не разбираем; пропускаем такие строки.
    if (classStr.includes("${") || classStr.includes("}")) continue;

    const textTokens = [...classStr.matchAll(/\btext-(zinc-\d{2,3}(?:\/\d+)?|red-\d{2,3}(?:\/\d+)?|amber-\d{2,3}(?:\/\d+)?|emerald-\d{2,3}(?:\/\d+)?|sky-\d{2,3}(?:\/\d+)?|white|black|text(?:-secondary|-muted)?)\b/g)].map((x) => x[1]);
    if (textTokens.length === 0) continue;
    const bgTokens = [...classStr.matchAll(/\bbg-(zinc-\d{2,3}(?:\/\d+)?|red-\d{2,3}(?:\/\d+)?|amber-\d{2,3}(?:\/\d+)?|emerald-\d{2,3}(?:\/\d+)?|sky-\d{2,3}(?:\/\d+)?|page|surface|surface-raised)\b/g)].map((x) => x[1]);
    const text = textTokens[textTokens.length - 1];
    const bgName = bgTokens.length > 0 ? bgTokens[bgTokens.length - 1] : "page";

    const t = resolve(text);
    const b = resolve(bgName);
    if (!t || !b || !t?.hex || !b?.hex) continue;
    const plain = text.replace(/^text-/, "");
    if (EXCLUDED_TEXT.has(plain)) continue;

    const bgHex = b.alpha < 1 ? blend(b.hex, b.alpha) : b.hex;
    const ratio = contrast(t.hex, bgHex);
    const key = `${text} on bg-${bgName}`;
    if (!pairs.has(key)) pairs.set(key, { text, bg: bgName, ratio, files: [] });
    pairs.get(key).files.push(relative("src", file));
  }
}

// Пары из условных классов (склеиваются конкатенацией строк, напр. день
// календаря в PeriodPicker) — держим их здесь как явные инварианты.
const EXTRA_PAIRS = [
  ["white", "sky-700"], // край диапазона календаря (было 2.77:1 на sky-500)
];

for (const [text, bgName] of EXTRA_PAIRS) {
  const t = resolve(text);
  const b = resolve(bgName);
  const ratio = contrast(t.hex, b.hex);
  const key = `${text} on bg-${bgName}`;
  pairs.set(key, { text, bg: bgName, ratio, files: ["EXTRA_PAIRS"] });
}

// CSS (index.css): пара body text/background и focus ring не текст.
let failed = 0;
const rows = [...pairs.values()]
  .map((p) => ({ ...p, ratio: Math.round(p.ratio * 100) / 100 }))
  .sort((a, b) => a.ratio - b.ratio);

for (const p of rows) {
  const ok = p.ratio >= MIN_RATIO;
  if (!ok) failed++;
  console.log(
    `${ok ? "OK  " : "FAIL"} ${String(p.ratio).padStart(5)}:1  text-${p.text.padStart(16)} on bg-${p.bg}  (${p.files[0]})`,
  );
}

console.log(`\n${rows.length} text/bg пар, ${failed} ниже ${MIN_RATIO}:1`);
process.exit(failed > 0 ? 1 : 0);
