# REPORT-MVP-7.2 REV1 — Значения индикаторов по умолчанию: исправление B1 (целые параметры)

## Статус

**Раунд 2 ревью: блокер B1 исправлен, готово к повторному ревью.**

- Ветка реализации: `agent/review/mvp-7.2` (от `master @ 22aa6f9`)
  - **`9ac093a`** — **pushed, in sync with origin** (подтверждение
    `git ls-remote` в «Публикация»).
  - Раунд 1: `59258e1` (проверен ревьюером, вердикт CHANGES REQUESTED — блокер
    B1); `9a8379b` — основная реализация I1–I5.
- База: `master @ 22aa6f9` — не изменялась.
- Отчёт: `agent/control:.agent/REPORT-MVP-7.2-REV1.md` — коммит в `agent/control`
  pushed.
- Самостоятельная приёмка не объявлялась — ревью за независимым ревьюером.

## Блокер B1 и исправление

**Суть B1.** После снятия запасных значений (I4) проверка `validate_spec_args`
смотрела только на отсутствие (`None`), поэтому период `0`/`-5` и целочисленные
параметры (`fast = 0`) проходили валидацию и сохранение (201/`valid: true`), а
падали в расчёте (`ZeroDivisionError` для периода 0, тихо пустой результат для
`-3`) или считались без ошибки в бэктесте/живом цикле бота.

**Исправление (только математическая необходимость; диапазоны Veles не
вводились, новая семантика не создавалась).**

1. **Бэкенд** — `backend/app/strategies/indicators.py:validate_spec_args` и
   новый хелпер `_require_positive_int`:
   - период (для индикаторов с `uses_period`) и все целочисленные параметры
     каталога (`type == "int"`) должны быть **целыми ≥ 1**; иначе `ValueError`
     с русским сообщением: «Индикатор RSI: параметр «период» должен быть целым
     числом не меньше 1.»;
   - параметры типа `float` (K у Bollinger) **не ограничены** (при `k = 0`
     расчёт не падает) — граница оставлена аррифметической, не семантической;
   - числовые строки и целые float (`"12"`, `12.0`) по-прежнему принимаются:
     расчёт всегда приводил их `int(...)`, а старые конфиги/JSON-режим могли их
     содержать; `True`, дробные (`12.5`) и нечисловой текст — ошибка.
   - Точки применения те же, что и для отсутствующих параметров (I4/I5):
     `POST /api/strategies` и `/validate` → **422**; бэктест — **422**
     (`backtests.py::_validation_message`); старт бота — **409**
     (`StrategyLoadError`); прямой вызов `indicator_series` — `ValueError`
     (вместо `ZeroDivisionError`/пустого результата).

2. **Форма** — `frontend/src/components/FilterGroupEditor.tsx`:
   `collectMissingIndicatorArgs` применяет те же правила:
   - поле периода/целого параметра получает ошибку «Период должен быть целым
     числом не меньше 1.» / «Параметр «…» должен быть целым числом не меньше
     1.», отправка блокируется (`requireIndicatorArgs` в
     `StrategyFormPage.tsx`);
   - числовые строки допустимы (JSON-режим, бэкенд их принимает); float-параметры
     (K) не проверяются.

## Тесты (добавлены в раунде 2)

- `backend/tests/test_indicators.py`:
  - `test_zero_or_negative_period_raises_explicit_error` — `indicator_series`
    с RSI `0`/`-5`, SMA `-3`, MACD `fast=0` → `ValueError`, русское сообщение;
  - `test_validate_spec_args_rejects_zero_or_negative` — `validate_spec_args`:
    RSI `0`/`-5`, MACD `fast=0` → ошибка; BOLLINGER `k=0.0`, SMA `"20"`,
    MACD `fast="12"` и `fast=12.0` — принимаются (числовые строки и целые
    float не ломаются).
- `backend/tests/test_mvp70_api.py`:
  - `test_zero_or_negative_indicator_params_rejected_422` — `POST
    /api/strategies` и `/validate` с RSI `period=0` и `period=-5` → **422** с
    русским сообщением; `/validate` с MACD `fast=0` → **422**.
- `frontend/src/lib/form.test.ts` (vitest + jsdom):
  - B1: SMA `period=0`/`-5` → ошибка у поля `…arg1.period`; MACD `fast=0` →
    ошибка `…params.fast`;
  - числовая строка `"20"` не порождает ошибку (JSON-режим), `2.5` — ошибку.

## Валидация (полный прогон на месте)

| Проверка | Результат |
|---|---|
| `pytest -q` | **580 passed, 1 skipped** (было 577/1 в раунде 1; +3 теста) |
| `ruff check app tests scripts` | без замечаний |
| `alembic heads` | `0006_stop_loss` (один head) |
| `npm test` | **29 passed** (6 файлов; было 27) |
| `npm run build` | OK |

## Изменённые файлы (раунд 2, 5 файлов)

- `backend/app/strategies/indicators.py` — `_require_positive_int`,
  `validate_spec_args` (целые ≥ 1);
- `backend/tests/test_indicators.py`, `backend/tests/test_mvp70_api.py` — тесты
  B1;
- `frontend/src/components/FilterGroupEditor.tsx` — `isPositiveInt` и проверки в
  `collectMissingIndicatorArgs`;
- `frontend/src/lib/form.test.ts` — vitest-тесты B1.

Проверено, что поведение I1–I5 раунда 1 не изменилось: значения по умолчанию,
источники (`veles`/`project`), предзаполнение формы и сообщения об отсутствующих
параметрах остались прежними (регрессия — существующий снимок чисел в
`test_catalog_defaults_keep_prechange_numbers`).

## Ограничения и примечания

- Граница «≥ 1» — только для целых параметров и только по математической
  необходимости; диапазоны значений, семантика Veles, формулы индикаторов и
  контракты I1–I5 не менялись.
- Внешнего ревью ожидается повторная проверка: `validate` для `0`/`-5` и
  формы с `0` (как указано в вердикте).
