# Veles-MOEX — Независимое ревью: MVP-8.0

## Вердикт (раунд 1)

**ACCEPT**

Принятая реализация: `e8e3149b291f25060637c3bf1920975995ab5b6f` (`agent/review/mvp-8.0`, запушена, совпадает с origin)
База: `master @ a08c489`
Отчёт: `.agent/REPORT-MVP-8.0.md` (по-русски — §8 соблюдено)
PR #40; CI (backend, frontend) на `e8e3149` — success.
Ревьюер: Claude, 2026-10-09

## Независимый прогон

| Проверка | Результат |
|---|---|
| `npm ci` / `npm test` | **81 passed** (11 файлов) |
| `npm run build` | успешно; JS 284.18 КБ (gzip 87.33 КБ) |
| `npm audit --omit=dev` | **0 vulnerabilities** (было 2 moderate на react-router 6) |
| `npm ls` | `react-router-dom@7.18.4` → `react-router@7.18.4` |
| backend | менялся только заголовок `requirements.lock`; CI backend (ruff, pytest, alembic) зелёный; Кодер: 607 passed, 1 skipped |
| Настоящий nginx 1.24 с конфигом из ветки (`nginx -t` + curl, раздача собранного `dist`) | см. ниже |

## Проверка nginx (curl на реальном сервере)

- `/` → `Cache-Control: no-cache`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, CSP.
- `/assets/<hash>.js` → `Cache-Control: public, max-age=31536000, immutable`, `Vary: Accept-Encoding`, `nosniff`, CSP; с `Accept-Encoding: gzip` → `Content-Encoding: gzip` (290 926 → 103 125 байт).
- SPA-маршрут `/bots` → 200 с теми же заголовками; несуществующий `/assets/nope.js` → 404.
- Браузер (Playwright) через этот nginx: переходы по всем разделам меню, прямая ссылка `/strategies/new`, открытие календаря «Период» — **нарушений CSP и ошибок страницы нет**. В коде нет `style=`/`eval`/`innerHTML`, поэтому минимальная политика ничего не блокирует.
- Живой прогон в Docker на ключе песочницы выполнил Кодер (контейнеры healthy, 270 бумаг, заголовки, страницы, скриншоты в `.agent/screenshots/MVP-8.0/`).

## Проверка контракта

- **G1**: `node:22-alpine`, `COPY package.json package-lock.json`, `npm ci`.
- **G2**: gzip, кэш `/assets/` и `no-cache` для HTML, заголовки безопасности повторены в обоих `location` (учтено правило `add_header`); CSP минимальная.
- **G3**: `requirements.lock` пересобран на Python 3.12.11; набор версий не изменился, обновлена шапка.
- **G4**: react-router 7.18.4 в библиотечном режиме без SSR, импорты не менялись; тесты, сборка и ручной проход зелёные.
- **G5**: стратегии, счета и бумаги грузятся независимо, у каждого поля своя ошибка дословно; тест «брокер недоступен» есть.
- Vite/Vitest/Tailwind/React/TypeScript не трогались; интерфейс и тексты не менялись.

## Замечания (не блокеры)

- **M1.** Размер бандла вырос с 268 до 284 КБ (gzip 82 → 87 КБ) из-за react-router 7. Для локального приложения приемлемо.
- **M2.** Dev-уязвимости остаются (14: vite/vitest/tailwind и др.) — в образ не попадают, закрываются следующим MVP (Vite/Vitest).
- **M3.** В `gzip_types` указан `application/javascript`; если в будущем образ nginx отдаст JS как `text/javascript`, сжатие JS пропадёт. Добавить `text/javascript` при следующей правке конфига (на текущем образе сжатие подтверждено).
