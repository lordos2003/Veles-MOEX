# REPORT-MVP-7.1-REV3 — Исправление по ревью раунда 3 (B8)

## Статус

**Исправление выполнено, готово к повторному ревью (раунд 4).**

- Ветка реализации: `agent/review/mvp-7.1`
  - **`366f09c`** — **pushed, in sync with origin** (подтверждение
    `git ls-remote` в конце отчёта).
- Проверенная реализация в раунде 3: `fdb1175`; вердикт: **CHANGES REQUESTED**,
  один новый блокер B8 (`.agent/REVIEW-MVP-7.1.md`, раунд 3, коммит `ef6cdf2`).
- B4 и B6 (раунд 2) — приняты ревьюером в раунде 3 (проверены вживую), в этом
  раунде не трогались; B8 — единственная правка.
- База: `master @ 795f4ed`; `master` не изменялся.
- Отчёт: `agent/control:.agent/REPORT-MVP-7.1-REV3.md` — коммит в `agent/control`
  pushed.

## Что исправлено

### B8. Страница бота при свежем браузере слала ~230 запросов в секунду

Две причины, обе подтвердились:

1. `frontend/src/lib/settings.ts`, `getPollIntervalMs()`: `Number(null) === 0`
   при отсутствующем ключе `veles.ui.poll_interval_ms` в `localStorage`,
   и `0` проходил проверку `>= 0` — `DEFAULT = 5_000` не применялся никогда.
2. `frontend/src/pages/BotsPage.tsx`, `BotDetailPage`: `window.setInterval(..., getPollIntervalMs())`
   без защиты `pollMs <= 0` (в списке ботов защита была, на странице — нет);
   интервал `0` превращался в бесконечный цикл запросов (то же — при явном
   «выкл» из списка).

Исправления:

- `getPollIntervalMs()`: отсутствующий/пустой/нечисловой/отрицательный ключ →
  `DEFAULT`; явный `"0"` → `0` («выкл», остаётся валидным).
- Новый общий хук `frontend/src/lib/usePolling.ts` (единый источник для списка
  и страницы, как просил ревьюер):
  - `usePollInterval()` — состояние интервала из `localStorage` + сохранение
    при смене (список ботов теперь реально персистит выбор «5/10/30 секунд»:
    раньше выбор жил только в state, а страница бота читала `localStorage` —
    именно из-за этого они расходились);
  - `usePolling(tick, pollMs)` — интервал **вообще не создаётся** при
    `pollMs <= 0`; `tick` обязан быть стабильным (`useCallback`), чтобы
    интервал не пересоздавался на каждом рендере.
- `BotsPage` (список) и `BotDetailPage` (страница) переведены на этот хук:
  у страницы деталей удалён второй источник «interval из getPollIntervalMs()
  на каждом рендере».

Тесты (все — новые):

- `frontend/src/lib/settings.test.ts` (vitest + jsdom): нет ключа → `5000`;
  `""` → `5000`; мусор (`abc`, `Infinity`) → `5000`; `-5` → `5000`;
  `"0"` → `0`; `setPollIntervalMs`/`getPollIntervalMs` round-trip.
- `frontend/src/pages/BotsPage.test.tsx` (vitest + jsdom + testing-library +
  **fake timers**; мок `../api`, `MemoryRouter`): на `/bots/1`
  - пустой `localStorage` (default `5000`): за 4999 мс — ровно 1 запрос
    `GET /api/bots/1`, на 5000-й мс — второй (один за период);
  - явный `"0"`: после начальной загрузки за 20 с повторных запросов нет.

## Проверки

| Проверка | Результат |
|---|---|
| `npm test` (vitest) | **22 passed** (5 файлов; в раунде 3: 15 — добавлены B8 ×7) |
| `npm run build` (tsc --noEmit + vite build) | **OK** |
| `pytest` (backend, venv) | **570 passed, 1 skipped** (backend не менялся) |
| `ruff check app tests scripts` | **All checks passed** |
| `alembic heads` | `0006_stop_loss (head)` — один head |
| дифф от `fdb1175` | только фронтенд: `settings.ts`, `usePolling.ts` (новый), `BotsPage.tsx`, 2 новых теста |

## Известные ограничения

- Playwright e2e/скриншоты по-прежнему не выполнялись (пакета playwright в
  проекте нет; живой прогон на чистом профиле браузера — обязательная часть
  проверки ревьюера, раунд 3 её явно повторит).
- Запасные значения индикаторов в расчёте оставлены (B5, решение владельца) —
  без изменений.
- Остальные ограничения раундов 1–3 не изменились (см. `.agent/REPORT-MVP-7.1.md`,
  `-REV1`, `-REV2`).

## Соответствие AGENTS.md

- Ветка/задача: `agent/review/mvp-7.1` от `master @ 795f4ed`, `master` не изменялся.
- Veles-семантика/контракты не менялись: backend не затронут; правка чисто
  фронтендовая (настройка опроса UI, U5) — значения по умолчанию не введены.
- Брокер-нейтральность не нарушена.

## Публикация

```
git push origin agent/review/mvp-7.1    # 366f09c (pushed, in sync with origin)
git push origin agent/control
git ls-remote origin agent/review/mvp-7.1 agent/control
```

Подтверждение `git ls-remote` (2026-10-07, после push):

```
366f09c<полный-SHA>	refs/heads/agent/review/mvp-7.1
<REV3-CONTROL-SHA>	refs/heads/agent/control
```

- `agent/review/mvp-7.1` = локальный `366f09c` — **in sync with origin**.
- `agent/control` = локальный `<REV3-CONTROL>` — **in sync with origin** (в ветке:
  ревьюерские `ef6cdf2` (раунд 3) и `05bf50c` (PROJECT_STATE); коммит этого отчёта
  добавлен).
