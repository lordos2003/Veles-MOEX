# REPORT-MVP-7.2 — Значения индикаторов по умолчанию: явно в схеме и форме, без скрытых запасных значений в расчёте

## Статус

**Реализация завершена, готово к ревью (раунд 1).**

- Ветка реализации: `agent/review/mvp-7.2` (от `master @ 22aa6f9`)
  - **`59258e1`** — **pushed, in sync with origin** (подтверждение
    `git ls-remote` в «Публикация»).
  - Предыдущий коммит: `9a8379b` — основная реализация I1–I5;
    `59258e1` — глобальный обработчик 422 для чистых русских сообщений.
- База: `master @ 22aa6f9` (содержит принятый MVP-7.1); `master` не изменялся.
- Отчёт: `agent/control:.agent/REPORT-MVP-7.2.md` — коммит в `agent/control`
  pushed.
- Самостоятельная приёмка не объявлялась — ревью за независимым ревьюером.

## Контракт I1–I5: что сделано

### I1. Единая таблица значений по умолчанию с источником

Единственный источник правды — каталог в `backend/app/strategies/indicators.py`:

- `IndicatorDef` — запись каталога (name, series, uses_*, `period_default`,
  `period_default_source`);
- `IndicatorParamDef` — параметр (name, type, required, `default`,
  `default_source`); фабрика `_param()` объявляет все параметры
  `required=True` (I4);
- `INDICATOR_CATALOG` — 12 индикаторов со значениями ровно из утверждённой
  владельцем таблицы (см. ниже). Расчётные функции больше не содержат этих
  чисел — они берут их из конфига как обязательные аргументы (`validate_spec_args`
  + `indicator_series`), поэтому каталог и расчёт не могут разойтись.

| Индикатор | Параметры по умолчанию | Источник |
|---|---|---|
| RSI | период 14 | **veles** |
| BOLLINGER | период 20, K 2 | **veles** |
| SMA | период 20 | project |
| EMA | период 9 | project |
| MACD | fast 12, slow 26, signal 9 | project |
| ATR | период 14 | project |
| CCI | период 20 | project |
| WILLIAMS_R | период 14 | project |
| CMO | период 14 | project |
| MFI | период 14 | project |
| STOCHASTIC | период 14, k_smooth 3, d_smooth 3 | project |
| ADX | период 14 | project |

### I2. Каталог отдаёт значения

- `backend/app/strategies/schemas.py`: `IndicatorParamResponse` + `default`
  (`int | float`) и `default_source` (`Literal["veles", "project"]`);
  `IndicatorResponse` + `period_default` и `period_default_source`
  (`None`, когда индикатор не использует период).
- `backend/app/api/strategies.py`: `GET /api/strategies/indicators` заполняет
  эти поля из `INDICATOR_CATALOG` — период и каждый параметр отдаются с
  `default` и `default_source`.

### I3. Форма предзаполняет с пометкой источника

- `frontend/src/components/FilterGroupEditor.tsx`:
  - при реальной смене индикатора (`setName`) период и параметры
    предзаполняются значениями каталога; **на загруженной сохранённой
    конфигурации ничего не перезаписывается** (предзаполнение только при
    смене имени), значения остаются редактируемыми (U4 не меняется);
  - `SourceMarker` под полем, когда значение равно дефолту каталога:
    «по умолчанию (Veles)» / «по умолчанию (выбор проекта)»; при изменении
    значения пометка исчезает.
- `frontend/src/lib/labels.ts`: `defaultSourceLabel()` — словарь пометок.
- `frontend/src/types.ts`: `DefaultSource = "veles" | "project"`, поля
  `default`/`default_source`/`period_default`/`period_default_source`.
- Правила U4 (интерфейс не придумывает значений, финансовые поля пустые)
  не менялись.

### I4. Расчёт без скрытых значений

- `backend/app/strategies/indicators.py`:
  - убраны все запасные значения: `or N`, `.get(..., N)` и значения по
    умолчанию в сигнатурах; `_macd_compute`/`_bollinger_compute`/
    `_stochastic_compute` читают `params["fast"]`, `params["k"]`,
    `params["k_smooth"]` и т. д. напрямую;
  - `validate_spec_args(name, period, params)` — каталог-дривенная проверка:
    отсутствует период/параметр → `ValueError` «Индикатор RSI: укажите
    параметр «период».» / «Индикатор MACD: укажите параметр «fast».»;
  - `indicator_series` вызывает `validate_spec_args` перед вычислением —
    уровень движка защищает прямой вызов, бэктест и live.
- `backend/app/strategies/config.py`: `@model_validator(mode="after")`
  `_validate_indicator_params` обходит все группы фильтров стратегии
  (entry, grid signal_groups, сигнальный TP, сигнальный стоп) и вызывает
  `validate_spec_args` для каждого индикаторного аргумента — покрывает
  `POST /api/strategies`, `PUT /api/strategies`, `POST /api/strategies/validate`,
  бэктест с inline-конфигом.
- `backend/app/main.py`: глобальный обработчик `RequestValidationError`
  убирает префикс pydantic «Value error, » из сообщений 422 — в UI
  (frontend показывает `item.msg` как есть) приходит чистое русское
  сообщение с индикатором и параметром; форма 422 (loc/type) сохраняется
  для пофильдовой подсветки.

### I5. Существующие конфиги — без миграции

Миграция данных не делалась. Версия стратегии без обязательного параметра
даёт явную ошибку:

- `POST /api/backtests` по `strategy_version_id`: 422
  (`backend/app/api/backtests.py`, `_validation_message`) — «Индикатор RSI:
  укажите параметр «период».» вместо прежнего 500/молчаливой подстановки;
- старт бота: `StrategyLoadError` → 409 с сообщением
  «strategy version N (vN) has an invalid configuration: Индикатор RSI:
  укажите параметр «период».» (`backend/app/bots/strategy.py`);
- пользователь создаёт новую версию с явными значениями (форма уже
  предзаполняет их из каталога).

## Перепроверка документации Veles (перед реализацией)

- `help.veles.finance/ru/filters` → **404**; `help.veles.finance/ru/filters/`
  → **404**; `help.veles.finance/ru/filters/general/` → только общая
  информация о фильтрах + «Подробная справка по каждому фильтру доступна
  в редакторе бота — кнопка "?"»; `help.veles.finance/ru` → навигация,
  без справочника индикаторов.
- Локальный `Veles Help Center — engineering reference.md` (стр. 116):
  «RSI default period is 14; flexible mode exposes period, interval, method
  and shift» — единственный подтверждённый дефолт.
- BOLLINGER 20/2: утверждённая таблица задания ссылается на
  `help.veles.finance/ru/filters` (BB: дефолт 20 и 2); на публичных
  страницах подтвердить не удалось (404), **противоречий с документацией
  не найдено** — значение оставлено по утверждённой владельцем таблице
  (`veles`). RSI 14 — подтверждено (`veles`). Остальные — выбор проекта
  (владелец), в UI и коде помечены `project`, за Veles не выдаются.
- Документированных значений, отличающихся от таблицы I1, не обнаружено —
  вопрос владельцу по этому пункту не требуется.

## Тесты

Backend (`backend/tests/`):

- `test_indicators.py`:
  - `test_catalog_defaults_are_explicit_with_sources` — полная таблица I1
    (значения + источники + `required`);
  - `test_missing_required_period_raises_explicit_error`,
    `test_missing_required_param_raises_explicit_error` — отсутствие
    параметра → ошибка, а не подстановка;
  - `test_catalog_defaults_keep_prechange_numbers` — регрессия: на 80-барной
    серии результаты индикаторов с параметрами из таблицы совпали с
    до-рефакторинговыми значениями (снимок в тесте);
  - существующие тесты (`test_all_indicators_return_full_series`,
    `test_indicator_output_selector`) переведены на явные значения каталога.
- `test_mvp71_api.py`: `GET /api/strategies/indicators` отдаёт
  `default`/`default_source`/`period_default`/`period_default_source`;
  каждый элемент каталога считается на fake-барах с его дефолтами.
- `test_mvp70_api.py`: `POST /api/strategies` и `POST /api/strategies/validate`
  без обязательного параметра → 422, русское сообщение с индикатором и
  параметром, **без** «Value error»; бэктест старой версии без параметра →
  422, новая версия с явным периодом → 200.
- `test_strategy_live_integration.py`: старая версия без обязательного
  параметра → `StrategyLoadError` с русским сообщением (I5, старт бота).

Frontend (vitest + jsdom):

- `frontend/src/components/FilterGroupEditor.test.tsx` (новый, 5 тестов):
  выбор RSI → предзаполнено 14 + пометка «по умолчанию (Veles)»; смена
  периода убирает пометку; выбор MACD → 12/26/9 с тремя пометками
  «по умолчанию (выбор проекта)», поля периода нет; смена параметра
  убирает его пометку; смена индикатора сохраняет timeframe/shift.
- `frontend/src/lib/form.test.ts`: фикстура каталога обновлена под новые
  поля (`default`, `default_source`, `period_default`, `period_default_source`),
  B5/I4 проверка блокировки пустых значений сохранилась.

## Проверки

- `pytest` (backend, venv): **577 passed, 1 skipped** (9.1 s).
- `ruff check app tests scripts`: **All checks passed**.
- `alembic heads`: **`0006_stop_loss` (head)** — миграций нет.
- `npm test` (frontend): **27 passed** (6 files).
- `npm run build`: `tsc --noEmit` + vite build — **OK**.
- Дифф от merge-base `22aa6f9` просмотрен: только файлы задачи
  (backend: indicators/schemas/config/api/bots/main + тесты; frontend:
  типы, labels, FilterGroupEditor + тесты).

## Наблюдения (вне задачи, формулы не менялись)

- ADX: значение линии `adx` на первых барах — сумма Уайлдера, не среднее
  (поведение существовало и до рефакторинга, `_wildered`); формулы не
  трогались (scope discipline), отмечено как наблюдение.
- Сообщение `StrategyLoadError` при старте бота сохранило существующую
  английскую обёртку («strategy version … has an invalid configuration:»);
  русская часть (текст по индикатору) — внутри. Существующий контракт
  ошибок не менялся.

## Публикация

```
git push origin agent/review/mvp-7.2    # 9a8379b, 59258e1 (pushed, in sync with origin)
git push origin agent/control
git ls-remote origin agent/review/mvp-7.2 agent/control
```

Подтверждение `git ls-remote` (2026-10-07, после push):

```
5d1fd1c01f3f9bdc2dc0f94e9a22e0afb47896a0	refs/heads/agent/control
59258e1bfe2227056c26a6f5b25128354231a42d	refs/heads/agent/review/mvp-7.2
```

- `agent/review/mvp-7.2` = локальный `59258e1` — **in sync with origin**.
- `agent/control` = локальный `5d1fd1c` — **in sync with origin** (в ветке:
  `98a4d47` TASK-MVP-7.2; `5d1fd1c` — коммит этого отчёта вместе с
  обновлённым `PROJECT_STATE.md`).
