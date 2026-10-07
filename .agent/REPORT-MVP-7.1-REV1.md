# REPORT-MVP-7.1-REV1 — Исправления по ревью раунда 1 (B1–B7)

## Статус

**Исправления выполнены, готово к повторному ревью (раунд 2).**

- Ветка реализации: `agent/review/mvp-7.1`
  - **`53592c9`** — **pushed, in sync with origin** (подтверждение
    `git ls-remote` в конце отчёта).
- Проверенная реализация в раунде 1: `7d662be`; вердикт: **CHANGES REQUESTED**,
  обязательные исправления B1–B7 (`.agent/REVIEW-MVP-7.1.md` в коммите
  `67380e9` на `origin/agent/control`).
- База: `master @ 795f4ed`; `master` не изменялся.
- Отчёт: `agent/control:.agent/REPORT-MVP-7.1-REV1.md` — коммит в `agent/control`
  pushed.

## Что исправлено (по пунктам ревью)

### B1. Стратегии и счета не сохраняются в PostgreSQL

- `backend/app/strategies/service.py`: `StrategyService.create()` и
  `StrategyService.update()` — после `flush()` добавлен `await self._session.commit()`.
- `backend/app/services/accounts.py`: `AccountService.sync_from_broker()` — после
  `flush()` добавлен `await self._session.commit()` (это же покрывает открытие
  счёта песочницы: счёт появляется локально через эту синхронизацию).
- Проверены остальные записывающие пути: `InstrumentService.sync_from_broker`
  коммитит (было), `BotRepository` (create/update_state/update_deposit/
  update_strategy_version/delete) коммитит (было) — больше незафиксированных
  транзакций в записывающих путях API не найдено.
- Новый тест `backend/tests/test_mvp71_rev1.py` (3 теста): API над file-based
  SQLite с **новой сессией на каждый запрос**; читает **новой сессией** после
  запроса:
  - `POST /api/strategies` → строка `Strategy` + ровно одна версия v1 видны
    из новой сессии, конфигурация совпадает с `StrategyConfig` (сравнение через
    `model_validate(...).model_dump()` — с дефолтами модели);
  - `PUT /api/strategies/{id}` → версий становится 2 (`[2, 1]`), у последней
    `dca_grid.levels == 3`, всё читается новой сессией;
  - `POST /api/accounts/sync` (фейковый брокер) → счёт с
    `external_account_id == "ext-ns"` виден новой сессией.

### B2. `docker compose up` падал на чистой базе (ревизия 0002 > 32 символов)

- Идентификатор ревизии `0002_instrument_fields_and_market_candles` (41 символ)
  укорочен до **`0002_instrument_fields_candles`** (30 символов) в
  `backend/alembic/versions/0002_instrument_fields_and_market_candles.py`
  (`revision`, docstring) и `0003_live_execution_state.py` (`down_revision`,
  «Revises»); README.md и backend/README.md обновлены.
- Безопасность: на PostgreSQL (и SQLite) цепочка `0001 → 0002 → 0003` после
  переименования нигде не применялась — если бы 0002 когда-то применилась, на
  PostgreSQL она бы упала сама (`StringDataRightTruncationError`), т.е.
  переименование не переписывает применённую историю.
- Прогон `alembic upgrade head` на PostgreSQL не выполнялся: локального
  PostgreSQL в этой среде нет (тест ревизий пропускается без БД — по указанию
  ревьюера «Если есть возможность»; живой прогон ревьюер повторит сам).
- Новый тест `backend/tests/test_mvp70_launch.py::test_alembic_revision_ids_fit_version_column`:
  все `revision` ≤ 32 символов и в цепочке ровно одна голова.

### B3. Бэктест молча подставлял нулевые комиссии и 30-дневный период

`frontend/src/pages/BacktestPage.tsx`:

- `from`/`to` больше **не предзаполняются** последними 30 днями (`useState("")`),
  палитра подстановок удалена.
- Пустые поля (`instrument`, `timeframe` при отсутствии таймфрейма в конфигурации,
  `from`, `to`, `deposit`, `makerFee`, `takerFee`, `slippage`) — ошибка **у
  поля** (`fieldErrors`), запрос **не отправляется**; значения `"0"` больше не
  подставляются — в payload уходят только введённые значения.
- Плейсхолдеры оформлены как примеры («например, 0.0003», «например, 100000»,
  «например, 2026-01-01T10:00»), чтобы не выглядеть значениями (неблокирующее
  замечание ревью).

### B4. Поля со значением по умолчанию в схеме показаны как «не выбрано»

- `frontend/src/lib/schema.ts::initialValue`: pydantic v2 эмитит
  `{"$ref": "#/$defs/X", "default": ...}` — `default` является **соседом**
  `$ref`, а не частью разрешаемого узла. Теперь `default` сначала читается с
  исходного узла (`hasDefault(node)` → возврат до `resolveRef`); для
  совместимости сохранён и прежний вариант — `default` внутри разрешённого узла
  `$defs`. Дублирующий `default`-резолв после `resolveRef` удалён.
- Новые тесты `frontend/src/lib/form.test.ts` (2 кейса):
  - пара `($ref + default)` даёт значение в начальном состоянии формы
    (`direction` = `LONG`, `method` = `at_bar_close`);
  - `propertyMetas` видит `defaultValue` у узла с `$ref`.

### B5. Пустой период индикатора молча становился 20 / 14 / …

- `frontend/src/components/FilterGroupEditor.tsx`:
  - поле «Период» отмечено **обязательным**, когда `entry.uses_period` (плюс
    проводка ошибки по пути `...argN.period`);
  - параметры каталога отмечены **обязательными** (все параметры каталога —
    используемые; `required` в каталоге остаётся флагом движка, форма не
    полагается на него);
  - добавлен обходчик `collectMissingIndicatorArgs(config, catalog)` — находит
    все узлы `{kind: "indicator", name}` и проверяет `period` (при
    `uses_period`) и параметры каталога; пути ошибок совпадают с путями полей.
- `frontend/src/pages/StrategyFormPage.tsx`: перед `Проверить` и `Сохранить`
  конфигурация проверяется обходчиком — при незаполненных параметрах показываются
  ошибки у полей и сообщение «Заполните обязательные параметры индикаторов…»,
  запрос не отправляется.
- **Запасные значения в расчёте не тронуты** (по указанию ревьюера): SMA 20,
  EMA 9, RSI 14, MACD 12/26/9, Bollinger 20/k2, Stochastic 14/3/3, ADX 14
  остаются fallback-значениями валидатора; изменение этого — отдельное решение
  владельца (зафиксировано здесь и остаётся в известных ограничениях).
  Исторические конфигурации без периода продолжают работать как раньше.
- Новые тесты `frontend/src/lib/form.test.ts` (3 кейса): обходчик находит
  пустой период и пустые параметры по нужным путям; заполненные индикаторы и
  другие `kind` ошибок не дают; без каталога (недоступен) блокировки нет.

### B6. На странице бота не было обещанных действий

- Новый компонент `frontend/src/components/BotSettingsPanel.tsx` + хук
  `useBotDisplayMeta()`; встроен **и в карточки списка ботов**, **и на страницу
  бота** (`frontend/src/pages/BotsPage.tsx`):
  - **изменить депозит** — `PATCH /api/bots/{id}` (положительное число;
    отдельная кнопка «Убрать депозит» — явный `null`, правило C5);
  - **сменить версию стратегии** — `PATCH {strategy_version_id}` со списком
    версий текущей стратегии (по одной стратегии бота);
  - **удалить** — `DELETE /api/bots/{id}` через `ConfirmDialog` с подтверждением.
  - По правилу R5 кнопки смены версии/удаления **неактивны с причиной**, когда
    бот не остановлен или есть незакрытая сделка (сделка на странице бота
    известна сразу; в списке подтягивается `GET /api/bots/{id}/deal`);
    ответ 409 сервера по-прежнему показывается дословно.
- Отображение: **тикер** инструмента (`/api/instruments` → id→ticker/FIGI),
  **название счёта** (`/api/accounts` → id→name/account_id) и **номер** версии
  стратегии (`/api/strategies/{id}/versions` → id→{стратегия, номер}; id версий
  глобально уникальны) — и в списке, и на странице («Стратегия: Имя · версия N»
  вместо прежнего «версия {id}»).

### B7. Неверная подсказка у тейк-профита

- `frontend/src/pages/StrategyFormPage.tsx` + `frontend/src/lib/labels.ts`:
  подсказка «Процент прибыли» исправлена — **«Процент прибыли от
  средневзвешенной цены позиции (D4)»** (раньше: «Один процент от текущей
  цены (E1)» — E1 относится к стопу).
- Остальные подсказки проверены: `exit.stop_loss.percent` (E1: сверх перекрытия
  сетки от цены первого ордера) и `exit.stop_loss.stop_bot_after` (E3) —
  корректны; ссылок на неверные контракты больше нет.

## Отклонение (флаг из раунда 1)

Отклонение раунда 1 — `id: int | None` в `InstrumentResponse` — **принято
ревьюером** («Отклонение «id в InstrumentResponse» принимается…», REVIEW раунда 1).
Изменений не требуется, поле остаётся.

## Проверки

| Проверка | Результат |
|---|---|
| `pytest` (backend, venv) | **570 passed, 1 skipped** (в раунде 1: 566/1; добавлены 3 теста B1 и 1 тест B2) |
| `ruff check app tests scripts` | **All checks passed** |
| `alembic heads` | `0006_stop_loss (head)` — один head |
| `npm test` (vitest) | **10 passed** (1 файл; в раунде 1: 5 — добавлены B4 ×2 и B5 ×3) |
| `npm run build` (tsc --noEmit + vite build) | **OK** |
| диффы B1–B7 от `7d662be` | просмотрены, изменений вне исправлений нет |

## Известные ограничения

- e2e на Playwright и скриншоты по-прежнему не выполнены: пакета playwright в
  проекте нет, а живой прогон требует поднятых PostgreSQL/uvicorn/vite
  (контракт U8 допускает; ревьюер выполняет живой прогон сам).
- Запасные значения индикаторов в расчёте оставлены (B5) — решение владельца
  зафиксировано в REPORT-MVP-7.1-REV1 и REPORT раунда 1.
- Остальные ограничения раунда 1 не изменились (см. `.agent/REPORT-MVP-7.1.md`).

## Соответствие AGENTS.md

- Ветка/задача: `agent/review/mvp-7.1` от `master @ 795f4ed`, `master` не изменялся.
- Veles-семантика/контракты D/C/S/N/L/E/R не менялись: backend-изменения
  только в `commit()` записывающих путей и переименовании ревизии миграции;
  семантических правил не касались. Запасные значения расчёта сохранены.
- Финансовые значения в UI не предзаполняются: комиссии/депозит/период
  бэктеста — пустые обязательные поля с ошибками (B3).
- Форма не вводит значений: только ввод пользователя или `default` схемы (B4);
  параметры индикаторов — обязательные (B5), без подстановки дефолтов.
- Брокер-нейтральность не нарушена: тикер/имя счёта берутся из внутренних
  `/api/instruments` и `/api/accounts`.

## Публикация

```
git push origin agent/review/mvp-7.1    # 53592c9 (pushed, in sync with origin)
git push origin agent/control
git ls-remote origin agent/review/mvp-7.1 agent/control
```

Подтверждение `git ls-remote` (2026-10-05, после push):

```
53592c9d30478784cecd52156a4056e6bc23caf5	refs/heads/agent/review/mvp-7.1
ba1e2031e36cef8627227123f14e97a9f73059c3	refs/heads/agent/control
```

- `agent/review/mvp-7.1` = локальный `53592c9` — **in sync with origin**.
- `agent/control` = локальный `ba1e203` — **in sync with origin** (в ветке:
  ревьюерский `67380e9` с `.agent/REVIEW-MVP-7.1.md`, `3145d71` (REPORT-REV1),
  merge `33dbdab`; `ba1e203` — коммит этого отчёта).
