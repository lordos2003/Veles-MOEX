# Veles-MOEX — Отчёт Кодера: MVP-8.0 «Гигиена сборки и безопасность интерфейса (по аудиту 2026-10-09)»

## Реализация

- Задача: `agent/control:.agent/TASK-MVP-8.0-TOOLING-HYGIENE.md`
- Ветка реализации: `agent/review/mvp-8.0`
- База: `master @ a08c489`
- HEAD: `e8e3149b291f25060637c3bf1920975995ab5b6f` (**запушена, в синхроне с origin** — проверено `git ls-remote`)
- Коммиты (каждый пункт — отдельный коммит):
  - `f37b260` — G1: образ интерфейса — `node:22-alpine`, `COPY package-lock.json`, `npm ci`;
  - `96e3a3d` — G2: nginx — gzip, кэш `assets/`, индекс `no-cache`, заголовки безопасности и CSP;
  - `b9f5a01` — G3: `requirements.lock` пересобран на Python 3.12.11 (версии без изменений);
  - `41c47dc` — G4: `react-router-dom` 6.26.2 → 7.18.4 (библиотечный режим, импорты без изменений);
  - `e8e3149` — G5: независимая загрузка стратегий/счетов/бумаг на «Боты → создать» (замечание M1 ревью MVP-7.7).

Изменено 7 файлов: `backend/requirements.lock`, `docker/frontend.Dockerfile`, `docker/nginx.conf`, `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/pages/BotsPage.tsx`, `frontend/src/pages/BotsPage.test.tsx`.

## Что изменено по пунктам

### G1. Воспроизводимая сборка интерфейса

`docker/frontend.Dockerfile`: базовый образ `node:20-alpine` → `node:22-alpine` (совпадает с Node 22 в CI); копируются `package.json` **и `package-lock.json`**; вместо `npm install` — `npm ci`. Сборка теперь детерминирована по lock-файлу и проходит на той же мажорной версии Node, что и CI.

### G2. nginx: сжатие, кэш, заголовки безопасности, CSP

`docker/nginx.conf`:

- **gzip**: `gzip on`, `gzip_types` — `text/plain text/css application/javascript application/json image/svg+xml`, `gzip_min_length 1024`, `gzip_vary on`.
- **Кэш**: `location /assets/` — `Cache-Control: public, max-age=31536000, immutable` + `try_files $uri =404`; `location /` — `Cache-Control: no-cache` (index.html всегда перевалидируется, что защищает от устаревших хешей).
- **Заголовки безопасности** (на уровне `server`): `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; connect-src 'self'`.
- Важная деталь: `add_header` внутри `location` **заменяет** унаследованный список заголовков от `server`, поэтому безопасностные заголовки повторены в обоих `location` (`/assets/` и `/`). Это указано комментарием в конфиге, чтобы будущие правки не «потеряли» заголовки.
- Инлайн-скриптов/стилей в приложении нет (Vite собирает внешние файлы), поэтому минимальный CSP не блокирует ничего.

### G3. `requirements.lock` на Python 3.12

Шапка переписана: «Generated from a Python 3.12.11 venv (as the image and CI) with `pip freeze`». Сам lock **не повышал версии**: старый набор ограничений (`-c requirements.lock`) установлен в чистом venv Python 3.12.11 → `pip freeze` дал тот же набор 38 пакетов, что был записан (проверено пакетно; в файле сохранён исходный регистр имён). Т.е. изменение — только фиксация происхождения и платформы; версии не изменились.

### G4. react-router 6 → 7 (библиотечный режим)

`frontend/package.json` + lock: `react-router-dom` `^6.26.2` → `^7.18.4`; в lock `react-router@7.18.4` (зависимость re-export).

- По официальному CHANGELOG v7: `react-router-dom` в v7 — это re-export `react-router`; импорты `react-router-dom` **не менялись** (задача разрешает менять только то, что требует пакет).
- Требования пакета выполнены: node ≥ 20 (образ 22, CI 22), react ≥ 18 (у нас 18.3.1).
- Используется библиотечный режим (`BrowserRouter` + `Routes`, без data-режима/SSR) — это поддерживаемый вариант v7.
- future-флаги v6 (`v7_relativeSplatPath`, `v7_startTransition` и др.) в v7 стали поведением по умолчанию — в коде включать ничего не нужно.
- `npm ls`: `react-router-dom@7.18.4` → `react-router@7.18.4`.

### G5. Независимая загрузка данных на «Боты → создать» (M1)

`frontend/src/pages/BotsPage.tsx` (компонент `CreateBotPanel`): вместо одного `Promise.all([strategies, accounts, instruments])` — три независимых async-блока с общим `cancelled`-флагом. Состояния: `strategies/accounts/instruments: X | null` (null = ещё не загружено) + отдельные `strategiesError/accountsError/instrumentsError`. Каждый блок рендерит свою ошибку под своим полем; недоступность `/api/accounts` больше **не блокирует** список бумаг и стратегий. Все последующие обращения к спискам переведены на `(x ?? [])`.

Тест в `BotsPage.test.tsx`: `/api/accounts` бросает «Брокер недоступен: нет токена» → бумаги (SBER) и стратегия загружаются, ошибка счетов показана дословно.

## Проверки

| Проверка | Результат |
|---|---|
| `npm ci` (локально и в образе) | успешно |
| `npm test` (vitest) | **81 passed** (11 файлов; было 80 — добавлен тест G5) |
| `npm run build` (tsc + vite) | успешно; dist: JS 284.18 kB / gzip 87.33 kB, CSS 15.64 kB / gzip 3.67 kB |
| `npm audit` | см. ниже |
| `pytest` (Python 3.12.11, backend) | **607 passed, 1 skipped** |
| `ruff check app tests scripts` (точная команда CI) | All checks passed |
| `alembic heads` | ровно одна голова: `0007_first_candle_dates` |
| Live-прогон в Docker (чистая БД) | контейнеры healthy, см. ниже |

### npm audit (до/после)

| | Всего | moderate | high | critical |
|---|---|---|---|---|
| до (react-router-dom 6.26.2) | 16 | 7 | 7 | 2 |
| после (react-router-dom 7.18.4) | **14** | 5 | 7 | 2 |

Все найденные уязвимости — в **dev-зависимостях** (vitest/tinypool, esbuild/vite, braces/micromatch/tailwindcss, postcss-selector-parser, source-map-js) и в production-образ не входят (nginx раздаёт статику из `dist`, node_modules не собирается). Обновление Vite/Vitest/Tailwind/TypeScript — вне скоупа задачи (отдельные MVP); зафиксировано как известное ограничение.

### Живой прогон (docker compose down -v → up -d --build; все контейнеры healthy)

- nginx-образ фронтенда собран из нового Dockerfile (node:22 + npm ci) и раздаёт на `127.0.0.1:5173`.
- **Заголовки/кэш/сжатие** (curl):
  - `/` → `Cache-Control: no-cache` + все security-заголовки;
  - `/assets/index-CWXXONnk.js` → `Cache-Control: public, max-age=31536000, immutable`, `Vary: Accept-Encoding`, security-заголовки;
  - с `Accept-Encoding: gzip` → `Content-Encoding: gzip` для JS и CSS; index.html (< 1 КБ) не сжимается — ожидаемо при `gzip_min_length 1024`;
  - несуществующий `/assets/...` → 404;
  - `/api/...` проксируется на backend (проверено на `/api/runtime`).
- **Страницы** (IAB-браузер, http://127.0.0.1:5173): Обзор, Стратегии, форма «Новая стратегия», Боты, форма создания бота, Бэктест, «Песочница и счета» — все рендерятся полностью при новом CSP (внешние чанки грузятся, инлайнов нет; ошибок страниц не зафиксировано). Навигация по меню (SPA, react-router 7) работает.
- **G5 вживую**: синхронизировано 270 инструментов; на «Боты → создать» поле «Ценная бумага» — поиск «сбер» → «Найдено: 2 из 270» → SBER — Сбербанк. Счета брокера загрузились (2 песочничных счёта; у обоих `id=null`, поэтому в селект «Счета (локальный)» попадают только сохранённые — в этой среде их нет, выбор пуст, ошибок нет). Стратегий в чистой БД нет (список пуст, без ошибки). Ветка «счета недоступны» покрыта юнит-тестом G5.

### Скриншоты (в `agent/control:.agent/screenshots/MVP-8.0/`)

- `00-overview.png` — Обзор после синхронизации: T-Invest подключен, 2 счета, позиция, рынок;
- `01-strategies.png` — Стратегии (пустой список);
- `02-strategy-form.png` — форма «Новая стратегия» (в т.ч. «Ценная бумага»);
- `03-bots.png` — Боты (список, автообновление);
- `04-bots-create.png` — форма создания бота: все три секции загружены независимо;
- `05-bots-create-sber.png` — «сбер» → «Найдено: 2 из 270» → SBER — Сбербанк;
- `06-backtest.png` — Бэктест (дефолты комиссий 0.003/0.003/0.001, P3 MVP-7.7);
- `07-sandbox.png` — Песочница и счета.

## Ограничения и известные замечания

1. **Уязвимости dev-зависимостей** (14: 5 moderate / 7 high / 2 critical) остаются: все в vitest/tinypool, esbuild/vite, braces/tailwindcss и др. Устранение требует обновления Vite/Vitest/Tailwind — вне скоупа MVP-8.0 (отдельные MVP). Прод-образ их не содержит.
2. **CSP минимальный** (`default-src 'self'; frame-ancestors 'none'; connect-src 'self'`). Если позже появятся инлайн-скрипты/стили, сторонние CDN или WebSocket к другому хосту — CSP потребует ревизии; сейчас приложению он не мешает (проверено живым прогоном).
3. **`add_header` в `location`** отменяет унаследованные заголовки — при добавлении новых `location` в nginx.conf нужно не забыть повторить security-заголовки (помечено комментарием в конфиге).
4. **Кэш assets immutable**: для очень старых вкладок возможен 404 устаревшего хеша (новый index.html отдаётся с `no-cache` и ссылается на актуальные хеши, поэтому на практике не проявляется).
5. `ruff check .` по всему репозиторию находит предсуществующие `I001` в `alembic/env.py` — они вне проверяемого CI набора (`app tests scripts`) и не связаны с изменениями MVP-8.0 (backend-код не менялся).
6. Поведение приложения и контракты (Veles-семантика, брокер-нейтральность, Decimal, UTC и т.д.) не менялись: backend затронут только `requirements.lock`.

## Публикация

- `git push origin agent/review/mvp-8.0` — успешно; `git ls-remote origin agent/review/mvp-8.0` = `e8e3149b291f25060637c3bf1920975995ab5b6f` = локальный HEAD (в синхроне).
- Отчёт и скриншоты — в `agent/control` (этот коммит).
- PR: `agent/review/mvp-8.0` → `master` (CI: ruff, pytest, alembic heads, vitest, build).
