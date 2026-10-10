# Veles-MOEX — Отчёт Кодера: MVP-8.2 «Tailwind 4, дизайн-токены и доступность интерфейса»

## Реализация

- Задача: `agent/control:.agent/TASK-MVP-8.2-TAILWIND4-A11Y.md`; основание — `AUDIT-FRONTEND-2026-10-09.md` (D1–D5, этап 4, этап 7).
- Ветка реализации: `agent/review/mvp-8.2`
- База: `master @ c87435a` (`origin/master`, `git ls-remote origin master`)
- HEAD: `196a76c429bab43866c0c2cca39e0d9e92ee5f64` (**запушена, в синхроне с origin** — проверено `git ls-remote`)
- Коммиты (каждая часть — отдельный коммит):
  - `937c50b` — Часть 1: Tailwind 3.4 → 4.3.3 через `@tailwindcss/vite` (CSS-first; `npm audit` 7 → 0);
  - `a63adc8` — Часть 2a: токены A0, единый фокус A3, фон/тема A5;
  - `ff408d2` — Часть 2b: контраст A1, подписи A2, цели A4, клавиатура A6;
  - `6b19022` — Часть 2c: тесты подписей и клавиатуры, скрипт WCAG-контраста (`npm run check:contrast`);
  - `196a76c` — Часть 2d: live-аудит axe (см. ниже) — программное имя чекбокса и уровень заголовка секции.

## Часть 1 — миграция Tailwind 4 (`937c50b`)

Версии: `tailwindcss` `^3.4.4` → `^4.3.3`; добавлен `@tailwindcss/vite` `^4.3.3` (последняя stable на npm на дату; без beta/rc). `postcss.config.js` и `tailwind.config.js` удалены — при выборе `@tailwindcss/vite` конфигурация становится CSS-first в `src/index.css` (`@import "tailwindcss"`, `@theme`), PostCSS-путь не нужен (T1).

Правки, потребовавшиеся по официальному upgrade guide (T2) — только они, без «заодно»-рефакторинга:

1. **`frontend/vite.config.ts`** — добавлен плагин `tailwindcss()` (единственное изменение конфигурации).
2. **`frontend/src/index.css`** — `@tailwind base/components/utilities` → `@import "tailwindcss"`; в `@layer base` вернуто два прежних preflight-поведения v3, изменённых в v4: `border-color: var(--color-gray-200, currentColor)` (в v4 дефолт — `currentColor`) и `cursor: pointer` для `button:not(:disabled)` / `[role="button"]` (в v4 — `cursor: default`).
3. **`frontend/src/components/FormControls.tsx`** — `focus:outline-none` → `focus:outline-hidden` (переименование утилиты v3 → v4).
4. **`frontend/README.md`** — зафиксирована совместимость браузеров Tailwind 4: Safari 16.4+, Chrome 111+, Firefox 128+ (T4).

Остальные 6000+ строк классов не менялись; визуально Часть 1 — 1:1 (скриншоты `10-…-after1` против `00-…-before`, отличий нет).

## Часть 2 — токены и доступность (A0–A6)

### A0. Токены (`a63adc8`)

В `@theme` (`frontend/src/index.css`) объявлены семантические токены на базе существующих zinc-значений (без изменения видимых цветов):

| Токен | Значение | Исходный цвет |
|---|---|---|
| `--color-page` | `#09090b` | zinc-950 |
| `--color-surface` | `#18181b` | zinc-900 |
| `--color-surface-raised` | `#27272a` | zinc-800 |
| `--color-border` | `#3f3f46` | zinc-700 |
| `--color-border-soft` | `#27272a` | zinc-800 |
| `--color-text` | `#f4f4f5` | zinc-100 |
| `--color-text-secondary` | `#d4d4d8` | zinc-300 |
| `--color-text-muted` | `#a1a1aa` | zinc-400 |
| `--color-accent` | `#0369a1` | sky-700 |
| `--color-accent-bright` | `#38bdf8` | sky-400 |
| `--color-error` | `#f87171` | red-400 |
| `--color-warning` | `#fbbf24` | amber-400 |
| `--color-success` | `#34d399` | emerald-400 |

Токены применены в общих компонентах (`FormControls`, `InstrumentPicker`, `PeriodPicker`, `App`) и местах, затронутых A1–A5 (по контракту — без массовой замены). `App` → `main className="min-h-screen bg-page text-text"`.

### A1. Контраст ≥ 4.5:1 (формула WCAG относительной яркости)

| Где было | Было | Отношение | Стало | Стало |
|---|---|---|---|---|
| Вторичный/приглушённый текст (подсказки, «Инструменты не загружены», Info-подписи, счётчики) | `text-zinc-500 #71717a` на surface `#18181b` | **3.67:1** ✗ | `text-text-muted #a1a1aa` | **6.91:1** ✓ |
| То же на фоне страницы `#09090b` | `#71717a` | **4.12:1** ✗ | `#a1a1aa` | **7.76:1** ✓ |
| День «с» календаря (PeriodPicker) | `white` на `bg-sky-500 #0ea5e9` | **2.77:1** ✗ | `white` на `bg-sky-700 #0369a1` | **5.93:1** ✓ |
| День «по» календаря | `white` на `bg-sky-600 #0284c7` | **4.10:1** ✗ | `white` на `sky-700` | **5.93:1** ✓ |
| Основной текст `--color-text #f4f4f5` на surface | — | **16.12:1** ✓ | — | — |
| Вторичный `--color-text-secondary #d4d4d8` на page | — | **13.46:1** ✓ | — | — |

Автоматизация: `frontend/scripts/check-contrast.mjs` (`npm run check:contrast`) — сканирует className-литералы, считает пары «текст/фон» с блендингом полупрозрачных фонов, порог 4.5:1. Результат: **24 пары текста/фона, 0 ниже 4.5:1**, выход 0. Исключения: `text-zinc-600` в заблокированных (`disabled`) элементах — WCAG 2.1 освобождает неактивные элементы; пара `white/sky-700` добавлена в `EXTRA_PAIRS` (генерируется через `bg-*` из каталога, а не из className).

### A2. Программные подписи

Единый механизм: контекст `FieldLabelContext` в `FormControls` — `Field` передаёт подпись потомку, контролы ставят `aria-label` (видимые тексты не менялись; `label` остался в DOM, `getByLabelText`-семантика существующих тестов не задета — все 81 старый тест зелёные без правок). Подписи получили:

- `TextInput`, `TextareaInput` (новый компонент, в т. ч. заменён `textarea` бэктеста), `NumberInput`, `SelectInput`, `NullableBoolInput`, `CheckboxInput` — из `Field`;
- `InstrumentPicker` — `aria-label` поля («Ценная бумага» и др.);
- `PeriodPicker` — сводное поле «Период», «Дата/Время начала/конца» в попапе;
- `StrategyFormPage` — textarea режима JSON: `aria-label="Конфигурация (JSON)"`;
- `BacktestPage` — textarea инлайн-конфигурации через `TextareaInput`.

### A3. Единый focus-visible

Глобальный `:focus-visible { outline: 2px solid var(--color-accent-bright); outline-offset: 2px; }` в базовом слое `index.css`; из полей убран `focus:outline-hidden` (остался только `focus:border-zinc-500`). Фокус на кнопках/ссылках/полях/элементах списка `InstrumentPicker` — один индикатор через токен `accent-bright` (9.29:1 на page).

### A4. Цели ≥ 32 px

`min-h-8` (+ по месту `min-w-8`/padding) добавлен: полям (`inputClass`), кнопкам (`Button`), кнопкам календаря и навигации месяцев, дням календаря, кнопкам и опциям «Быстрого выбора», пунктам списка `InstrumentPicker` (опция = `min-h-8`), селекту автообновления на «Ботах». Чекбокс: 16 px визуально при 32 px области (`box-content h-4 w-4 p-2`). Вёрстка таблиц и строк не сломана (скриншоты).

### A5. Фон и тема

`body { margin: 0; background-color: var(--color-page); color: var(--color-text); … }`, `:root { color-scheme: dark; }` — при светлой теме ОС белых подложек нет (проверено на светлой теме средствами ОС — скриншоты после 20-…).

### A6. Клавиатура

- `InstrumentPicker` — ARIA combobox-паттерн: `role=combobox/listbox/option`, `aria-expanded`, `aria-controls`, `aria-activedescendant`, `aria-selected`, `aria-autocomplete="list"`; фокус открывает список, ArrowDown/ArrowUp — подсветка, Enter — выбор, Escape — закрытие (тесты `InstrumentPicker.test.tsx`: 2 сценария).
- `PeriodPicker` — уже был кнопочным (Tab/Enter работают), проверено; дефектов не найдено.

## Тесты и проверки

| Проверка | Результат |
|---|---|
| `npm test` | **88 passed** (13 файлов) — 81 существующих без изменений + 7 новых (5 из `6b19022`, 2 из `196a76c`) |
| Новые тесты | `BacktestPage.test.tsx`: подписи всех полей бэктеста (по имени `getByRole`/`getByLabelText`), textarea в инлайн-режиме, listbox с options и `aria-activedescendant`; `InstrumentPicker.test.tsx`: клавиатура (2); `FormControls.test.tsx`: программное имя чекбокса из `Field`, `Section` → заголовок h2 |
| `npm run check:contrast` | 24 пары, 0 ниже 4.5:1 |
| `npm ci` | успешно; `npm audit` — **0 уязвимостей**; `npm audit --omit=dev` — **0** (цель выполнена; 7 записей цепочки tailwindcss 3 закрыты Частью 1) |
| `npm run build` | `tsc --noEmit` + `vite build` успешно |
| Бандл (gzip) | База `master`: JS 292.79 kB / 88.20, CSS 15.62 kB / 3.67 → Часть 1: CSS 20.43 / 4.76 (JS без изменений) → Часть 2 (финал): JS **293.86 kB / 88.47**, CSS **20.58 kB / 4.82**. Рост CSS — Tailwind 4 генерирует больше утилит (наследие), +JS 1.07 kB — aria-атрибуты/новый `TextareaInput`; поведение не менялось |
| `pytest` | 607 passed, 1 skipped (backend не менялся — контрольно) |
| `ruff check app tests scripts` | чисто (контрольно) |
| `alembic heads` | один head: `0007_first_candle_dates` (контрольно) |
| Версии | `tailwindcss` 4.3.3, `@tailwindcss/vite` 4.3.3; Vite 6.4.4, Vitest 4.1.11, `@vitejs/plugin-react` 4.7.0 — не изменены (совместимы) |

## Живой прогон (docker compose, прод-сборка)

Стек поднят (`veles_moex_frontend`/`backend`/`postgres`/`redis`), образ интерфейса пересобран с Частью 2d (`docker compose up -d --build frontend`, nginx, http://127.0.0.1:5173) — отдаёт `assets/index-B6DSbfq_.js` / `index-u7Ldky-R.css` (совпадает с локальной сборкой).

- **axe-core 4.14.0** (инъекция в IAB-браузер, все страницы, стандартные правила):

| Страница | До (`master`-бандл, Tailwind 3) | После (финал) |
|---|---|---|
| `/` (Обзор) | color-contrast 14, heading-order 1 | **0** |
| `/strategies` | color-contrast 1 | **0** |
| `/strategies/new` | color-contrast 6, label 14, select-name 5 | **0** |
| `/backtest` | color-contrast 3, label 3, select-name 3 | **0** |
| `/bots` | color-contrast 4 | **0** |
| `/sandbox` | color-contrast 13 | **0** |
| **Итого** | **67 узлов нарушений** (41 contrast, 17 label, 8 select-name, 1 heading-order) | **0** |

  «До»-бандл собран из `origin/master` (worktree, Tailwind 3.4 + Vite 6.4.4, JS 292.79 / CSS 15.62) и подложен в контейнер, после — возвращён финальный dist и перепроверен по SHA.
- **Промежуточный аудит (после 2a–2c, до 2d)** выявил 2 находки, устранённые в `196a76c`: чекбокс без программного имени (`label`, critical — `CheckboxInput` не читал контекст поля) и пропуск уровня заголовка (`heading-order`, moderate — секции `Section` были h3 после шапки h1; теперь h2, визуально не изменилось: классы те же).
- **Страницы и поведение**: все 6 страниц открываются (скриншоты 20–25); «Боты → создать» — панель «Новый бот» с именованными полями (26); «Бэктест» — инлайн-конфигурация `GAZP — Газпром`, period 05.01.2025–07.01.2025, `Данные для бэктеста доступны с: 23.01.2006`, POST `/api/backtests` → **результат отрисован** (капитал 100000 → 100000.00, PnL 0, сделок 0 — фильтров входа нет, ожидаемо) (27); `npm run dev` (Vite 6.4.4, порт 5174) — 200, react-refresh (проверено, сервер остановлен).
- **Скриншоты** — `agent/control:.agent/screenshots/MVP-8.2/`: `00-…-before` … `05-…-before` (до Части 1), `10-…-after1` … `15-…-after1` (после Части 1, визуально 1:1), `20-…-after2` … `25-…-after2` (финал), `26-bots-create-after2.png`, `27-backtest-run-after2.png`.

## Ограничения

1. **Hint-подсказки полей** («ⓘ …») остаются в `title` span — вспомогательные технологии надёжно их не озвучивают; задача требовала подписи контролов, не подсказок (зафиксировано как известное ограничение, вне контракта A2).
2. **`text-zinc-600` в заблокированных элементах** — 2.29:1, исключено из `check:contrast` и axe (WCAG 2.1 освобождает неактивные элементы); при разблокировке не встречается.
3. **Рост бандла** — CSS +4.96 kB raw / +1.15 gzip (Tailwind 4 генерирует больше утилит; визуальные токены 1:1 совместимы), JS +1.07 kB raw / +0.27 gzip (aria-атрибуты, `TextareaInput`). Значимых для лоада нет.
4. **Визуальная разница Части 2** — только из пунктов A1–A5: чуть светлее приглушённый текст (`zinc-400` вместо `zinc-500`), видимый фокус, кнопки/поля ≥ 32 px, `color-scheme: dark`.
5. **Veles-семантика не менялась**: фильтры/сигналы, DCA/Grid, PositionManager, Decimal, UTC, T-Invest read-only — исходники бизнес-логики не затронуты (diff — только стили/разметка/типы ARIA), backend без изменений.
6. **Контракты предыдущих MVP сохранены**: все 81 существующих теста зелёные без ослаблений; `entry`/`exit` и пр. поля бэктеста работают как раньше (проверено живым прогоном).

## Публикация

- `git push origin agent/review/mvp-8.2` — успешно; `git ls-remote origin agent/review/mvp-8.2` = `196a76c429bab43866c0c2cca39e0d9e92ee5f64` = локальный HEAD (в синхроне).
- Отчёт и скриншоты — в `agent/control` (этот коммит).
- PR: `agent/review/mvp-8.2` → `master` (CI: ruff, pytest, alembic heads, vitest, build).
