# TASK-MVP-8.0 — Гигиена сборки и безопасность интерфейса (по аудиту 2026-10-09)

## Статус

**ACCEPT (раунд 1, 2026-10-09)** — проверен `e8e3149`, PR #40; опубликовано: PR #40, merge `b9343e5`.

Контрольная ветка: `agent/control`
Ветка реализации: `agent/review/mvp-8.0` (от текущего `master` @ `a08c489`; SHA — `git ls-remote origin master`)
Основание: `.agent/AUDIT-FRONTEND-2026-10-09.md` (этап 1 + 2.1 + 3.2). Дата: 2026-10-09

## Зачем

Аудит интерфейса показал: образ интерфейса собирается без lock-файла, nginx без сжатия/кэша/заголовков безопасности, `react-router` 6.30 содержит moderate-advisories, `requirements.lock` собран на другом Python, чем образ. Поведение приложения **не меняется**.

## Контракт

Новой семантики Veles нет. Правила проекта и принятые контракты не меняются. Каждый пункт — отдельный коммит (чтобы откат был точечным).

### G1. Воспроизводимая сборка интерфейса
- `docker/frontend.Dockerfile`: копировать `package.json` **и** `package-lock.json`, ставить `npm ci`; базовый образ `node:22-alpine` (как в CI).
- Критерий: `docker compose build frontend` проходит; версии в образе = lock.

### G2. nginx: сжатие, кэш, заголовки
`docker/nginx.conf`:
- `gzip on` для текстовых типов (html, css, js, json, svg);
- хэшированные файлы `/assets/` — `Cache-Control: public, max-age=31536000, immutable`; `index.html` — `no-cache`;
- заголовки: `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY` и `Content-Security-Policy` (минимум: `default-src 'self'`; `frame-ancestors 'none'`; `connect-src 'self'`). Если интерфейс (стили Tailwind, график свечей, календарь) ломается из-за политики — ослабить **только нужную директиву**, обосновать в REPORT; не отключать CSP целиком без причины.
- Учесть: `add_header` в `location` отменяет унаследованные из `server` — заголовки должны быть и на `/api/`-ответах не требуются, но на `/` и `/assets/` — обязательны.
- Критерий: `curl -I` на `/` и на `/assets/<файл>` показывает заголовки; интерфейс работает (живой прогон, консоль браузера без нарушений CSP).

### G3. Python-lock
- Пересобрать `backend/requirements.lock` в окружении **Python 3.12** (как образ и CI); шапку файла обновить. Версии существенно не повышать без необходимости (если `pip freeze` на 3.12 даёт другие версии — привести в REPORT).
- Критерий: `pip install -c requirements.lock .` и `pytest`, `ruff`, `alembic heads` проходят на 3.12; образ backend собирается.

### G4. react-router 7
- `react-router-dom` → актуальная 7.x (stable, `latest`), режим библиотеки, **без SSR/data-режима**; импорты менять только если этого требует пакет. Прочитать официальный гайд миграции 6→7 и перечислить в REPORT, какие future-флаги/изменения применены.
- Критерий: `npm audit --omit=dev` — без записей уровня moderate и выше; все 80 тестов и `npm run build` зелёные; ручной проход по всем маршрутам (Обзор, Стратегии, форма, Боты, страница бота, Бэктест, Песочница) в живом прогоне.

### G5. Независимая загрузка данных на «Боты → создать»
(решение владельца по ревью MVP-7.7, замечание M1)
- В `CreateBotPanel` (`BotsPage.tsx`) стратегии, счета и бумаги грузятся **независимо**: сбой `/api/accounts` (брокер) не мешает загрузке бумаг и стратегий; ошибка показывается дословно и только для своего списка.
- Тест: брокер недоступен (`/api/accounts` → ошибка) — бумаги и стратегии доступны, у поля «Счёт» своя ошибка.

## Тесты и проверки
`npm ci`, `npm test`, `npm run build`; `pytest`, `ruff check app tests scripts`, `alembic heads` (одна голова); `npm audit --omit=dev`. Отчёт: результат `npm audit` (все зависимости) до/после — **dev-уязвимости vite/vitest не закрываются в этом MVP**, это следующий этап.

## Живой прогон (обязателен)
Чистая копия: `docker compose down -v` → `up -d --build`, ключ песочницы из веб-интерфейса проекта. Проверить: интерфейс открывается, все страницы работают, «Бэктест» запускается, «Боты → создать» с выбором бумаги; `curl -I` — заголовки; `curl -H 'Accept-Encoding: gzip' -I` — сжатие. Скриншоты в REPORT. Токен и ключи в REPORT/коммиты не попадают.

## Ограничения
Только сборка, nginx, lock и `react-router`; **не** обновлять Vite, Vitest, Tailwind, React, TypeScript (отдельные MVP). Дизайн и тексты интерфейса не менять. Не публиковать в `master`, не объявлять приёмку.

REPORT → `agent/control:.agent/REPORT-MVP-8.0.md` по-русски: pushed SHA, что изменено по G1–G5, результаты проверок и `npm audit`, ограничения.

## Публикация (обязательно, `AGENTS.md` §6)
```
git push origin agent/review/mvp-8.0
git push origin agent/control
git ls-remote origin agent/review/mvp-8.0 agent/control
```
Затем открыть PR `agent/review/mvp-8.0` → `master` (запустится CI). Без `--force` и rebase.
