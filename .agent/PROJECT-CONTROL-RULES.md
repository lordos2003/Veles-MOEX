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

**Обязательное правило проекта:** если ChatGPT формирует готовое задание для Кодера, пользователь не должен копировать текст вручную.

Порядок:
1. ChatGPT формирует точное задание.
2. ChatGPT публикует его непосредственно в GitHub репозитории `lordos2003/Veles-MOEX`.
3. Для рабочей задачи используется GitHub Issue или другой явный GitHub-артефакт, если текущий workflow требует иной формы.
4. Пользователю сообщается ссылка на опубликованное задание.
5. Кодер получает задание из GitHub.
6. После выполнения ChatGPT проверяет фактический commit и REPORT.

Для текущего workflow контрольная ветка — `agent/control`.

## 3. Не заставлять пользователя переносить инструкции вручную

Текст задания в сообщении ChatGPT может быть показан для пояснения, но это не является основным способом передачи задания кодеру.

Основной источник истины для задания — опубликованный GitHub-артефакт проекта.

## 4. Восстановление в новом чате

При начале нового чата по Veles-MOEX необходимо учитывать:
- `.agent/CODER-WORKFLOW.md`;
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

Каждое задание (`TASK-*.md`) заканчивается блоком «Publication» с командами push для своей ветки. Подробно: `.agent/CODER-WORKFLOW.md`, раздел «Mandatory push rule».

## 5c. Публикация принятой работы в master (редакция 2026-10-08)

Владелец (Олег, 2026-10-08) делегировал Claude, который ведёт проект, **все слияния, пуши и закрытие Issue**: полные права на `lordos2003/Veles-MOEX`, владельцу не нужно ничего сливать руками.

Порядок после ревью с вердиктом ACCEPT:

1. Если для приёмки нужна проверка на машине владельца (Docker, токен T-Invest и т. п.), владелец её выполняет и сообщает результат. Это проверка, а не разрешение на слияние.
2. Claude создаёт PR `agent/review/mvp-X` → `master` (в описании `Closes #N`, подпись Claude Code; голова PR = принятый SHA) и **сливает его сам** обычным merge-коммитом (не squash, не rebase) с указанием `sha` принятой реализации.
3. Claude записывает SHA слияния в `PROJECT_STATE.md` на `agent/control`, зеркалирует записи MVP в `master` (отдельный коммит или ветка `docs/mvp-X-records` и PR) и убеждается, что Issue закрыт.
4. Владельцу сообщается, что опубликовано (PR, SHA).

Границы делегирования: не публиковать работу без вердикта ACCEPT; не `--force`, не rebase публичных веток; не менять принятые контракты без решения владельца.

Если среда сессии заблокирует слияние (классификатор безопасности Claude Code может отклонять самослияние: «Self-Approval»), это ограничение стоит на стороне среды, не GitHub. Обход не предпринимается; Claude сообщает владельцу, что именно заблокировано, и предлагает резервный путь: PR создан, слияние по ссылке делает владелец. Постоянное решение — правило прав на стороне владельца в Claude Desktop для этой операции.

После публикации владельцу полезно переключить локальную копию: `git checkout master`, `git pull`, `docker compose up -d --build`, чтобы запуск шёл из `master`, а не из ветки ревью.

## 5b. Язык общения

Кодер общается везде по-русски: ответы владельцу, REPORT, сообщения коммитов, комментарии в Issue и PR. Код, идентификаторы и технические термины остаются на английском (`AGENTS.md` §8).

## 6. Правило для спецификаций и аудитов

Если для MVP существует specification в `docs/architecture/`, аудит должен сверять:
- acceptance criteria спецификации;
- фактическую реализацию;
- тесты;
- текущий `PROJECT_STATE.md`;
- устаревшие README/документацию.

Если спецификации нет, это должно быть явно отмечено в audit report; фактический код и git history проверяются по текущему `agent/control` baseline.
