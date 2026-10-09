# Veles-MOEX — Отчёт Кодера: MVP-8.1 «Обновление Vite, Vitest и @vitejs/plugin-react (dev-инструменты по аудиту 2026-10-09)»

## Реализация

- Задача: `agent/control:.agent/TASK-MVP-8.1-VITE-VITEST.md`
- Ветка реализации: `agent/review/mvp-8.1`
- База: `master @ 8ed7c9f`
- HEAD: `7d71c451cf1b82df0d925d8bd7250ae9414529d2` (**запушена, в синхроне с origin** — проверено `git ls-remote`)
- Коммиты (каждая ступень — отдельный коммит):
  - `caaa668` — V1: Vite 5.4 → 6.4.4, Vitest 2.1 → 3.2.7;
  - `7d71c45` — V2: Vitest 3.2 → 4.1.11 (тип `Mock` под v4), `source-map-js` 1.2.1 → 1.2.2.

Изменено 3 файла: `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/components/PeriodPicker.test.tsx`.

## Что изменено по ступеням

### V1 (`caaa668`): Vite 5 → 6, Vitest 2 → 3

`frontend/package.json`: `vite` `^5.4.0` → `^6.4.4`; `vitest` `^2.1.9` → `^3.2.7`. Lock-файл пересобран (`npm install` в чистом каталоге, затем `npm ci`).

- **Выбор версии (минимальная закрывающая):** Vite 6.4.4 — `previous` на npm; уязвимости `vite` (`path traversal` в optimized deps `.map`, `server.fs.deny` bypass на Windows, SSRF dev-сервера через `esbuild`) исправлены в 6.4.3+. Диапазон уязвимых версий — `<=6.4.2`, поэтому минимальна именно ветка 6.4.x. Версия 7/8 не даёт преимуществ для этой задачи (V2 по уязвимостям закрыт уже 6.4.4), риск перехода выше — остановился на 6.4.4.
- **Миграция Vite 5 → 6** (официальный guide, `vite.dev/guide/migration`): проверены разделы — требования Node (Vite 6: `^18.0.0 || ^20.0.0 || >=22.0.0` — совместимо с `node:22-alpine` в образе и Node 22 в CI), смена дефолтного `build.target` (`modules` → `baseline-widely-available`), удаление/устаревание отдельных опций (`css.codeSplit` и т. п.), Sass legacy API. **Применённых изменений конфигурации нет** — `vite.config.ts` не менялся (0 строк diff против базы; использует `defineConfig` из `vitest/config`, `test.environment: "node"`, `include: src/**/*.test.ts(x)`, `server.proxy /api` — всё осталось валидным для Vite 6).
- **Миграция Vitest 2 → 3** (release notes 3.0): проверены — `workspace` → `projects`, смена дефолтов `environment`, изменения `vi.mock` hoisting, удалённые API. Наш конфиг (`test.environment`, `include`) затронут не был, **изменений нет**.

### V2 (`7d71c45`): Vitest 3 → 4, `source-map-js`

`vitest` `^3.2.7` → `^4.1.11`; в lock `source-map-js` `1.2.1` → `1.2.2` (обновление `npm update source-map-js` — семвер-совместимое, без `--force`/`overrides`).

- **Почему сразу 4.x:** ступень 3.2.7 показывает, что `tinypool` (critical) и `vitest` (critical, через `@vitest/mocker`/`vite-node`) остаются — Vitest 3.x тянет `tinypool ^1.1.1`, исправленной 1.x-версии нет. Vitest 4.1.11 и 5.x `tinypool` не зависят вовсе; 4.1.11 — минимальная версия, закрывающая критичные записи. Требования Node: Vitest 4.1.11 — `^20.0.0 || ^22.0.0 || >=24.0.0` — совместимо с Node 22 (образ и CI); Vitest 5 требует `^22.12 || >=24` — совместимо по мажору, но node:22-alpine (npm 10.9.9) закрывает 22.x без 22.12 — риск, поэтому остановка на 4.1.11 (минимальная и достаточная).
- **Единственное изменение кода (по миграции Vitest 3 → 4):** в `PeriodPicker.test.tsx` тип пропа `Harness.onChange` изменён с `ReturnType<typeof vi.fn>` на `(from: Date | null, to: Date | null) => void`. Причина: в Vitest 4 тип `Mock` обобщён как `Mock<Procedure | Constructable>` и **не вызываемый** — `TS2348` в `tsc --noEmit`; сигнатура функции остаётся совместимой с `vi.fn()`. Остальные использования `vi.fn()` (в т. ч. `api.post as unknown as ReturnType<typeof vi.fn>`) типизацию проходят, т. к. используются только `.mock.calls`/matchers. Больше изменений по миграции (настройки `environment`/defaults, само-изоляция, снапшоты) не потребовалось.
- **`@vitejs/plugin-react`:** в манифесте остался `^4.3.1` (peerDependencies: `vite ^4.2.0 || ^5 || ^6 || ^7` — совместим с Vite 6.4.4, обновление не требуется). Резолв в lock — `4.7.0` (не изменился относительно базы). Мажоры 5/6 требуют Node ≥ 20.19/22.12 или Vite 8 — не нужны для закрытия уязвимостей.
- **`source-map-js` 1.2.2** закрывает high (event-loop DoS через indexed source-map sections) в транзитивных цепочках `postcss`/`jsdom`.

## `npm audit`: до/после

До (база `master @ 8ed7c9f`, после MVP-8.0): **14 записей — 2 critical, 7 high, 5 moderate**.

| Пакет | Уровень | Цепочка |
|---|---|---|
| `tinypool` | critical | vitest 2.x |
| `vitest` | critical | тянула tinypool / @vitest/mocker / vite-node / vite |
| `vite` | high | dev-сервер (path traversal, fs.deny bypass, esbuild SSRF) |
| `source-map-js` | high | postcss / jsdom |
| `esbuild` | moderate | vite 5 |
| `@vitest/mocker` | moderate | vitest 2 |
| `vite-node` | moderate | vitest 2 |
| `braces`, `chokidar`, `fast-glob`, `micromatch`, `tailwindcss` | high | tailwindcss 3 |
| `postcss-nested`, `postcss-selector-parser` | moderate | tailwindcss 3 |

После: **7 записей — 0 critical, 5 high, 2 moderate** (полный список — ниже; `npm audit --omit=dev` = **0**).

**Остаток (только цепочка tailwindcss 3 — вне скоупа задачи, закрывается переходом на Tailwind 4):**

| Пакет | Уровень | Причина (via) |
|---|---|---|
| `braces` | high | stack-exhaustion DoS (глубоко вложенные паттерны) |
| `chokidar` | high | via `braces` |
| `micromatch` | high | via `braces` |
| `fast-glob` | high | via `micromatch` |
| `tailwindcss` | high | via chokidar / fast-glob / micromatch / postcss-* |
| `postcss-nested` | moderate | via `postcss-selector-parser` |
| `postcss-selector-parser` | moderate | квадратичная сложность разбора селекторов |

Закрыты полностью: `tinypool`, `vitest`, `vite-node`, `@vitest/mocker`, `vite`, `esbuild`, `source-map-js` — **0 critical/high/moderate в цепочках vite/vitest/esbuild/tinypool/vite-node/@vitest/mocker** (критерий V2 выполнен). `npm audit fix --force` и `overrides` не использовались.

## Проверки

| Проверка | Результат |
|---|---|
| `npm ci` | успешно (215 пакетов; 7 уязвимостей — те же dev-остатки) |
| `npm test` | **81 passed** (11 файлов) — на обеих ступенях; ничего не удалено/не ослаблено |
| `npm run build` (`tsc --noEmit` + `vite build`) | успешно; dist: JS **292.79 kB / gzip 88.20 kB**, CSS 15.62 kB / gzip 3.67 kB |
| Бандл до/после | до (Vite 5.4): JS 284.18 kB / gzip 87.33 kB, CSS 15.64 / 3.67 → рост JS +8.61 kB raw / +0.87 kB gzip. Исходники приложения не менялись (diff — только тип в тесте); изменение — следствие инструментария Vite 6 (пересборка/минификация), поведение не менялось |
| `npm audit` | 14 (2 crit / 7 high / 5 mod) → **7 (0 crit / 5 high / 2 mod)**, остаток — tailwindcss 3 |
| `npm audit --omit=dev` | **0** (до и после) |
| `pytest` | 607 passed, 1 skipped (backend не менялся — контрольно) |
| `ruff check app tests scripts` | чисто (backend не менялся — контрольно) |
| `alembic heads` | один head (контрольно) |
| `tsconfig.json`, TypeScript 5.5, Tailwind 3.4, React 18.3, react-router 7 | **не изменены** |

## Живой прогон

Чистая копия: `docker compose down -v` → `up -d --build` (ключ песочницы передан через переменную окружения, в отчёт/коммиты не попадает). Сборка образа интерфейса (`node:22-alpine`, `npm ci`, Vite 6.4.4) — успешно; стек поднят, контейнеры healthy; 270 инструментов синхронизировано.

- **nginx (http://127.0.0.1:5173, прод-сборка под CSP):** заголовки безопасности (`X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, CSP `default-src 'self'; frame-ancestors 'none'; connect-src 'self'`), gzip для JS/CSS, `Cache-Control: immutable` для `assets/`, `no-cache` для index, прокси `/api` — на месте (наследие MVP-8.0, регрессии нет).
- **Страницы (IAB-браузер):** Обзор — T-Invest подключен, 2 песочничных счёта, позиция `RUB000UTSTOM`, рынок (ABIO — Артген, 43.4); Стратегии — «Стратегий пока нет»; форма «Новая стратегия» — все секции (основное, условия входа, сетка, ТП/выход, риск) с подсказками; Боты — «Ботов пока нет», автообновление; **«Боты → создать»** — панель «Новый бот», три секции загружены независимо (стратегии пусто — в чистой БД их нет; счета брокера не сохранены (`id=null`) — селект «Счёт (локальный)» пуст без ошибок; **поиск «SBER» → «Найдено: 2 из 270» → «SBER — Сбербанк»**, кнопка «Создать» заблокирована до заполнения — поведение MVP-8.0 не регрессировало); **«Бэктест»** — запущен через инлайн-конфигурацию (SBER, timeframe `1d` из конфигурации, период 3 месяца, депозит 100000, комиссии 0.003/0.003/0.001): результат получен — капитал 100000 → 95528.507107720, PnL 0, сделок 0, макс. просадка 0.1582 (без фильтров входа сделок нет — ожидаемо, важен сам прогон); «Песочница и счета» — 2 счёта tinvest (100000/500000).
- **`npm run dev` (отдельно):** Vite 6.4.4 dev-сервер (`http://localhost:5174`, proxy `/api` → backend) — 200, react-refresh, страницы рендерятся: Обзор (подключен, 2 счёта, позиция, рынок), навигация работает. Dev-режим не сломан. (Сервер слушает `[::1]` — стандартное поведение Vite `localhost`-host; конфиг не меняли.)
- **Скриншоты** — `agent/control:.agent/screenshots/MVP-8.1/`:
  `00-overview-nginx.png`, `01-overview-dev.png`, `02-strategies-nginx.png`, `03-strategy-new-nginx.png`, `04-bots-nginx.png`, `05-bots-create-nginx.png`, `06-backtest-nginx.png`, `07-sandbox-nginx.png`, `08-overview-dev.png`.

## Ограничения

1. **7 уязвимостей остаются** — вся цепочка `tailwindcss 3` (таблица выше, критерий V2 исключает её из задачи; закрывается переходом на Tailwind 4 — отдельный MVP). Все — dev-зависимости, в прод-образ не попадают (`npm audit --omit=dev` = 0).
2. **Бандл +3 % (JS)** — следствие смены инструментов сборки (Vite 5 → 6), не исходников: diff приложения отсутствует.
3. **`@vitejs/plugin-react` не обновлён по манифесту** (остался `^4.3.1`, резолв 4.7.0): peer-требования выполнены, уязвимостей у пакета нет; обновление до 5.x/6.x потребовало бы Vite 7/8 и Node ≥ 22.12 — вне минимально необходимого.
4. **Поведение приложения и контракты (Veles-семантика, брокер-нейтральность, Decimal, UTC и т. д.) не менялись** — затронуты только dev-инструменты и один тип в тесте.
5. Backend не изменялся (`pytest`/`ruff`/`alembic` — контрольные прогоны).

## Публикация

- `git push origin agent/review/mvp-8.1` — успешно; `git ls-remote origin agent/review/mvp-8.1` = `7d71c451cf1b82df0d925d8bd7250ae9414529d2` = локальный HEAD (в синхроне).
- Отчёт и скриншоты — в `agent/control` (этот коммит).
- PR: `agent/review/mvp-8.1` → `master` (CI: ruff, pytest, alembic heads, vitest, build).
