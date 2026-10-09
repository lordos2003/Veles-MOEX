# Veles-MOEX — Независимое ревью: MVP-8.1

## Вердикт (раунд 1)

**ACCEPT**

Принятая реализация: `7d71c451cf1b82df0d925d8bd7250ae9414529d2` (`agent/review/mvp-8.1`, запушена, совпадает с origin)
База: `master @ 8ed7c9f`
Отчёт: `.agent/REPORT-MVP-8.1.md` (по-русски — §8 соблюдено)
PR #43; CI (backend, frontend) на `7d71c45` — success.
Ревьюер: Claude, 2026-10-09

## Независимый прогон (Node 22.22.2)

| Проверка | Результат |
|---|---|
| `npm ci` | успешно |
| `npm test` | **81 passed** (11 файлов), ничего не удалено и не ослаблено |
| `npm run build` | успешно; JS 292.79 КБ (gzip 88.20 КБ) |
| `npm ls` | vite 6.4.4, vitest 4.1.11, @vitejs/plugin-react 4.7.0, esbuild 0.25.12 |
| `npm audit` (все) | **7** (5 high, 2 moderate); critical — нет; было 14 (2 critical) |
| Состав остатка | только `braces`, `chokidar`, `fast-glob`, `micromatch`, `tailwindcss`, `postcss-nested`, `postcss-selector-parser` — цепочка Tailwind 3 |
| `npm audit --omit=dev` | **0** |
| Dev-сервер (`vite`, порт 5175) | `/` и `/src/main.tsx` → 200; браузер: переходы по разделам, календарь «Период» открывается, ошибок консоли нет |

Backend не менялся (diff — `package.json`, `package-lock.json`, одна строка типа в тесте); CI backend зелёный. Живой прогон в Docker на ключе песочницы выполнил Кодер (сборка образа на `node:22-alpine`, nginx, все страницы, бэктест, `npm run dev`; скриншоты в `.agent/screenshots/MVP-8.1/`).

## Проверка контракта

- **V1**: две ступени отдельными коммитами (Vite 5→6.4.4 + Vitest 2→3.2.7; затем Vitest 3→4.1.11). Выбор версий обоснован: Vite 6.4.4 закрывает уязвимости dev-сервера, Vitest 4.x убирает зависимость от `tinypool`; Vite 7/8 и Vitest 5 не брались (Node ≥ 22.12 не гарантирован образом). Изменения конфигурации не потребовались (`vite.config.ts` без diff); единственное изменение кода — тип пропа в тесте под новый тип `Mock`.
- **V2**: в цепочках vite/vitest/esbuild/tinypool/vite-node/@vitest/mocker записей нет; остаток — только Tailwind 3, приведён таблицей; `--force` и `overrides` не использовались.
- **V3**: TypeScript, Tailwind, React, react-router, `tsconfig` не менялись; поведение и вид приложения те же.

## Замечания (не блокеры)

- **M1.** `@vitejs/plugin-react` не обновлялся (манифест `^4.3.1`, резолв 4.7.0) — совместим с Vite 6, уязвимостей нет; обновление потребовало бы Vite 7/8 и Node ≥ 22.12. Приемлемо.
- **M2.** Бандл вырос на 8.6 КБ (gzip +0.9 КБ) из-за Vite 6; код приложения не менялся.
- **M3.** Оставшиеся 7 записей закрываются только Tailwind 4 — отдельный MVP вместе с дизайн-токенами (аудит, этап 4).
