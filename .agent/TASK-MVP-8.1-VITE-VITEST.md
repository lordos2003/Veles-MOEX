# TASK-MVP-8.1 — Обновление Vite, Vitest и @vitejs/plugin-react (dev-инструменты)

## Статус

**ACCEPT (раунд 1, 2026-10-09)** — проверен `7d71c45`, PR #43; опубликовано: PR #43, merge `d974ecc`.

Контрольная ветка: `agent/control`
Ветка реализации: `agent/review/mvp-8.1` (от текущего `master` @ `8ed7c9f`; SHA — `git ls-remote origin master`)
Основание: `.agent/AUDIT-FRONTEND-2026-10-09.md` (этап 2.2). Дата: 2026-10-09

## Зачем

`npm audit` (все зависимости) после MVP-8.0 показывает 14 записей, критичная — `tinypool` (через vitest 2.x), high — `vite` 5.x (path traversal в dev-сервере) и цепочка `braces/micromatch` (через tailwindcss 3). Это dev-инструменты, в образ не попадают, но их нужно обновить. Решение владельца (2026-10-09): делаем 8.1.

Текущие версии: vite 5.4.x, vitest 2.1.x, @vitejs/plugin-react 4.7.x. Целевая — **stable-ветки** (dist-tag `latest`/`previous` на npm); beta/rc/alpha/next не использовать.

## Контракт

Приложение, его поведение, дизайн и тексты **не меняются**. Новой семантики Veles нет.

### V1. Порядок и шаги
- Обновлять **ступенями**, после каждой — `npm ci`, `npm test`, `npm run build`, отдельный коммит. Ориентир: Vite 5 → 6.x (`previous`) → при необходимости выше; Vitest 2 → 3.x → 4.x; `@vitejs/plugin-react` — под выбранный Vite (по peerDependencies). Остановиться на **минимальной** версии, которая закрывает уязвимости, если более новая ломает сборку/тесты без явной пользы; обоснование (advisory, fixed-версия) — в REPORT.
- Перед каждой ступенью прочитать официальный migration guide / release notes (Vite, Vitest) и перечислить в REPORT применённые изменения конфигурации (`vite.config.ts`, `test` секция).
- Требования к Node (минимальные версии Vite/Vitest) сверить с `node:22-alpine` в образе и Node 22 в CI; если нужная версия Node выше, чем даёт образ/CI, — не обходить, а описать и остановиться на предыдущей ступени.

### V2. Критерий по уязвимостям
- `npm audit` (все зависимости): **нет записей critical и high в цепочках vite / vitest / esbuild / tinypool / vite-node / @vitest/mocker**.
- Записи в цепочке tailwindcss 3 (`braces`, `micromatch`, `fast-glob`, `chokidar`, `postcss-selector-parser` и т. п.) закрываются только переходом на Tailwind 4 — **в эту задачу не входят**; привести остаток в REPORT таблицей (пакет, уровень, цепочка). Не использовать `npm audit fix --force` и `overrides` без согласования.
- `npm audit --omit=dev` остаётся **0**.

### V3. Прочее
- `tsconfig.json`, TypeScript, Tailwind, React, react-router **не менять**.
- Если в `vite.config.ts` требуется миграция опций прокси/тестов (в т.ч. `test.environment`, `include`) — менять только то, что требует новая версия.
- Docker-образ: `npm ci` в `node:22-alpine` проходит, `dist` собирается, размер бандла в REPORT (до/после).

## Проверки
`npm ci`, `npm test` (≥ 81 тест, ничего не удалять и не ослаблять), `npm run build`; `npm audit` и `npm audit --omit=dev` до/после; `pytest`, `ruff check app tests scripts`, `alembic heads` (backend не меняется — контрольно).

## Живой прогон (обязателен)
Чистая копия: `docker compose down -v` → `up -d --build`, ключ песочницы из веб-интерфейса проекта. Проверить: образ интерфейса собирается, все страницы открываются, «Бэктест» запускается, «Боты → создать». Отдельно запустить `npm run dev` (Vite dev-сервер с прокси `/api`) и открыть интерфейс — dev-режим не должен сломаться. Скриншоты в REPORT. Токен и ключи в REPORT/коммиты не попадают.

## Ограничения
Только инструменты разработки и их конфигурация. Не публиковать в `master`, не объявлять приёмку.

REPORT → `agent/control:.agent/REPORT-MVP-8.1.md` по-русски: pushed SHA, ступени и версии, применённые изменения по migration guide, `npm audit` до/после (таблица остатка), результаты проверок, ограничения.

## Публикация (обязательно, `AGENTS.md` §6)
```
git push origin agent/review/mvp-8.1
git push origin agent/control
git ls-remote origin agent/review/mvp-8.1 agent/control
```
Затем открыть PR `agent/review/mvp-8.1` → `master` (запустится CI). Без `--force` и rebase.
