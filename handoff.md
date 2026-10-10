# Handoff: Veles-MOEX — роль архитектора/ревьюера — 2026-10-10

## Цель
Олег (владелец) развивает Veles-MOEX (github.com/lordos2003/Veles-MOEX) — клон Veles Finance для MOEX через T-Invest API. Его локальный ИИ «Кодер» пишет код. Моя роль: архитектор, автор задач, независимый ревьюер, публикатор (только после явного «да»/«публикуй» владельца).

## Текущее состояние
- Сделано: опубликованы MVP-7.5, 7.6, 7.7, 8.0, 8.1 (все ACCEPT с 1-го раунда, зеркала в master, Issues закрыты). Последний: 8.1 — PR #43, merge d974ecc.
- В процессе: **MVP-8.2 «Tailwind 4, токены, доступность» назначен Кодеру** (2026-10-10). Задача: `agent/control:.agent/TASK-MVP-8.2-TAILWIND4-A11Y.md`, Issue #45, коммит control 9decbdf. Ветка реализации: `agent/review/mvp-8.2`.
- Не начато: проверка 8.2 (ждём, пока Кодер запушит ветку и REPORT).

## Ключевые решения и ограничения
- Общение по-русски, кратко, прагматично. Claude in Chrome только в крайнем случае.
- Команды владельца: «проверь/проверяй» = ревью запушенной работы; «да/ок/публикуй» = публикация; «продолжим» = подготовить следующий MVP (варианты через AskUserQuestion).
- AGENTS.md: не выдумывать семантику Veles; не менять принятые контракты молча; Кодер обязан пушить обе ветки и указывать pushed SHA в REPORT; токены/ключи не в репозиторий.
- Коммиты: трейлеры `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` и `Claude-Session: https://claude.ai/code/session_01C1JFEwaQCwrJtohFiGHWw7`; PR-описания заканчиваются «🤖 Generated with [Claude Code](https://claude.com/claude-code)» + URL сессии.
- Принятые контракты C1–C7, D1–D7, S1–S6, N1–N3, L1–L4, E1–E5, R1–R8, U1–U12, H1–H4, F1, P1–P3, G1–G5, V1–V3 (см. PROJECT_STATE.md и REVIEW-*). Бэктест-дефолты комиссий: Maker 0.003, Taker 0.003, Slippage 0.001.

## Файлы и артефакты
- `/home/claude/veles-moex` — клон; ветка `agent/control` (PROJECT_STATE.md, `.agent/TASK-*`, `REVIEW-*`, `REPORT-*`, `AUDIT-FRONTEND-2026-10-09.md`).
- `master` — только принятое (HEAD c87435a после зеркала 8.1).
- Токены GitHub/T-Invest — в окружении сессии, в файлы не писать.

## Команды: как проверять (процедура ревью)
1. `git fetch origin; git ls-remote origin agent/review/mvp-8.2 agent/control master`; прочитать REPORT, diff против merge-base.
2. Worktree `/tmp/wtXX`; бэкенд: `uv venv -p 3.12`, `pytest`, `ruff check app tests scripts`, `alembic heads` (один head `0007_first_candle_dates`).
3. Фронтенд: `npm ci && npm test && npm run build`, `npm audit` и `npm audit --omit=dev` (цель 8.2: 0 записей).
4. Живой прогон UI: PostgreSQL 16 (`/usr/lib/postgresql/16/bin`, initdb от пользователя postgres), `TINVEST_SANDBOX=true uvicorn app.main:app --port 8000`, `npx vite --port 517x`, Playwright 1.56 (chromium `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`), `/api/accounts` стабить через route. Процессы убивать по PID, не `pkill -f`.
5. Публикация (после «публикуй»): `gh api -X PUT repos/lordos2003/Veles-MOEX/pulls/N/merge` с `sha`, merge_method=merge, «Closes #N»; обновить PROJECT_STATE/TASK, push control; зеркало записей в master через ветку `docs/mvp-X-records` и PR (автослияние после CI); закрыть Issue через PATCH state=closed.

## Открытые вопросы и риски
- Для 8.2 проверить: визуально 1:1 после Tailwind 4 (скриншоты до/после), контраст ≥4.5:1 (расчёт), подписи полей, фокус, цели ≥32px, `npm audit` = 0.
- Ручные проверки владельца в песочнице: события `OrderStateStream`; поведение сделки при удалении неисполненных заявок после сессии.
- Мелочи: `text/javascript` в nginx `gzip_types`; пресет «Весь период» показывает «—»; фильтр id!==null в InstrumentPicker.

## Следующие шаги (по порядку)
1. Ждать «проверь» от владельца → ревью MVP-8.2 по процедуре выше → REVIEW-MVP-8.2.md (ACCEPT/REJECT).
2. После «публикуй» — merge PR, зеркало, закрыть Issue #45, обновить PROJECT_STATE.
3. На «продолжим» — предложить следующий MVP: торговые функции (мульти-тейк, безубыток, TP/SL по сигналу, режим «Сигнал» live), надёжность live (перевыставление TP при рестарте, `FILLED -> UNKNOWN`, политика `GetStopOrders`, время свечей 4h/week/month), мелочи, CI `npm audit` + Playwright smoke, Dependabot; позже React 19 / TS 7 отдельно.

## Что НЕ делать
- Не публиковать без явного «да»/«публикуй» (при неоднозначном «1. да» — уточнить).
- Не использовать `--force`, rebase, `audit fix --force`, `overrides` без согласования.
- Не подставлять значения по умолчанию для семантики Veles, если документация их не задаёт.
