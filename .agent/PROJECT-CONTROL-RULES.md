# Veles-MOEX — Project Control Rules

## 1. Canonical working/audit reference

**`agent/control` is the canonical control branch and the default source of truth for current project tasks, audit instructions, specifications under review, control records, REPORTs, and acceptance status.**

When starting any new task, review, audit, or new chat:
- start from `agent/control`;
- inspect the relevant task/specification and `PROJECT_STATE.md`;
- use the current `agent/control` state as the baseline;
- inspect `agent/review/mvp-X` or `master` only when the task requires comparison.

**The user must not be asked to tell the coder where to find the current task or audit instructions.**

This rule applies to both implementation tasks and independent audits.

## 2. Задания кодеру публикуются напрямую

**Обязательное правило проекта:** если ChatGPT формирует готовое задание для OpenCode/кодера, пользователь не должен копировать текст вручную.

Порядок:
1. ChatGPT формирует точное задание.
2. ChatGPT публикует его непосредственно в GitHub репозитории `lordos2003/Veles-MOEX`.
3. Для рабочей задачи используется GitHub Issue или другой явный GitHub-артефакт, если текущий workflow требует иной формы.
4. Пользователю сообщается ссылка на опубликованное задание.
5. OpenCode/кодер получает задание из GitHub.
6. После выполнения ChatGPT проверяет фактический commit и REPORT.

Для текущего workflow контрольная ветка — `agent/control`.

## 3. Не заставлять пользователя переносить инструкции вручную

Текст задания в сообщении ChatGPT может быть показан для пояснения, но это не является основным способом передачи задания кодеру.

Основной источник истины для задания — опубликованный GitHub-артефакт проекта.

## 4. Восстановление в новом чате

При начале нового чата по Veles-MOEX необходимо учитывать:
- `.agent/OPENCODE-WORKFLOW.md`;
- этот файл;
- `PROJECT_STATE.md`;
- актуальное состояние `agent/control`.

Если создаётся новое задание кодеру, сначала публиковать его в GitHub, затем давать пользователю ссылку.

Если начинается аудит или review, сначала читать текущий `agent/control` и искать задание/спеку там.

## 5. Контроль и принятие

Стандартный поток остаётся:

`agent/control -> agent/review/mvp-X -> независимая проверка ChatGPT -> master`

ChatGPT не принимает работу только на основании заявления кодера. Проверяется фактический diff, тесты, архитектура, scope и REPORT.

## 5a. Работа сдана только после push в GitHub

Ревью проводится только по состоянию GitHub. Работа кодера считается сданной, когда:

- ветка `agent/review/mvp-X` запушена;
- REPORT закоммичен и запушен в `agent/control`;
- в REPORT указан запушенный SHA с пометкой «pushed, in sync with origin».

Push обычный, без `--force` и без rebase. При расхождении с GitHub: `git fetch origin` → `git merge origin/<ветка>` → push. `master` кодер не пушит никогда.

Каждое задание (`TASK-*.md`) заканчивается блоком «Publication» с командами push для своей ветки. Подробно: `.agent/OPENCODE-WORKFLOW.md`, раздел «Mandatory push rule».

## 6. Правило для спецификаций и аудитов

Если для MVP существует specification в `docs/architecture/`, аудит должен сверять:
- acceptance criteria спецификации;
- фактическую реализацию;
- тесты;
- текущий `PROJECT_STATE.md`;
- устаревшие README/документацию.

Если спецификации нет, это должно быть явно отмечено в audit report; фактический код и git history проверяются по текущему `agent/control` baseline.
