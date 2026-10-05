# REPORT-MVP-7.1 — Экраны: стратегии (полная форма), боты, сделка, бэктест, песочница

## Статус

**Готово к ревью (раунд 1).**

- Ветка реализации: `agent/review/mvp-7.1`
  - **`7d662be`** — **pushed, in sync with origin** (подтверждение
    `git ls-remote` в конце отчёта).
- База: `master @ 795f4ed`; `master` не изменялся.
- Отчёт: `agent/control:.agent/REPORT-MVP-7.1.md` — коммит в `agent/control` pushed.
- Вопрос к ревью по одному отклонению от рамки «backend меняется только в U2 и U3»:
  см. раздел «Отклонение (флаг для ревью)» — добавлен `id` в `InstrumentResponse`.

## Что сделано (по пунктам контракта)

### U1. Каркас приложения

- `react-router-dom` (v6) добавлен в `frontend/package.json`; других тяжёлых
  зависимостей нет (Vite/Tailwind/React остались как были).
- Разделы: **Обзор**, **Стратегии**, **Боты**, **Бэктест**, **Песочница и счета**
  (`frontend/src/App.tsx` — `NavLink` + `<Routes>`).
- Весь интерфейс по-русски; таблица терминов — ниже.
- Ошибки API показываются **дословно** (`detail` 4xx/5xx): `frontend/src/api.ts`
  (`ApiError`, `verbatimMessage`) — строковый `detail` как есть, массив
  «путь: сообщение»; все страницы выводят `err.message` без замены.
  Исключение только UA-текст в адресной строке — нет, всё как в ответе.
- Страницы: `frontend/src/pages/OverviewPage.tsx` (бывшая дефолтная, перенесена
  на `api.ts`, добавлен признак «сохранён» у счетов), `StrategiesPage.tsx`,
  `StrategyFormPage.tsx`, `BotsPage.tsx`, `BacktestPage.tsx`, `SandboxPage.tsx`.

### U2. Индикатор режима (безопасность)

- `GET /api/runtime` (backend, только чтение): `{sandbox, live_trading_enabled,
  tinvest_configured}` из настроек — `backend/app/api/runtime.py`,
  `backend/app/schemas/runtime.py`, подключён в `backend/app/api/router.py`.
  Тест: `backend/tests/test_mvp71_api.py::test_runtime_endpoint`.
- `frontend/src/lib/useRuntime.tsx` — загрузка `/api/runtime` + обновление раз в
  30 с; `frontend/src/components/ModeBadge.tsx` — плашка «Песочница» /
  «Боевой счёт» на всех страницах (в шапке), при боевом счёте +
  `live_trading_enabled` — постоянная красная плашка **«Реальные деньги»**;
  ошибка запроса выводится дословно.
- START бота в боевом режиме — только через окно подтверждения
  (`ConfirmDialog`, `frontend/src/pages/BotsPage.tsx`): текст подтверждения
  содержит счёт, инструмент, депозит. В песочнице подтверждение не требуется
  (кнопка «Старт»).

### U3. Каталог индикаторов (backend)

- `GET /api/strategies/indicators` — `backend/app/strategies/indicators.py`
  (рефакторинг в `INDICATOR_CATALOG` + dispatch), `backend/app/api/strategies.py`,
  `backend/app/strategies/schemas.py` (`IndicatorResponse`).
- Каталог строится тем же словарём, что и `indicator_series` (расчёт), поэтому
  каталог и расчёт не могут разойтись; значения по умолчанию в каталог **не
  вынесены** (например `rsi(period=14)` — период отдаётся параметром без
  default, AGENTS.md §2).
- Тест-сверка (`test_mvp71_api.py`): каждая запись каталога вычисляется через
  `indicator_series` на фейковых свечах; каждое имя, которое понимает
  `indicator_series`, присутствует в каталоге (прямая и обратная проверка).

### U4. Стратегии — полная форма

- Список стратегий (`StrategiesPage.tsx`): название, число версий, дата
  обновления; карточка (`/strategies/:id`): история версий, просмотр любой
  версии (только чтение, JSON), «Изменить» — редактирование создаёт **новую
  версию** (`PUT /api/strategies/{id}`), старые не меняются.
- Форма (`StrategyFormPage.tsx`) — 6 блоков:
  1. **Основное**: название, описание, направление, таймфрейм, `lookback_bars`,
     `instrument_id`;
  2. **Условия входа**: метод (`at_bar_close` / `per_minute`), редактор групп
     фильтров (`FilterGroupEditor.tsx`) — группы ИЛИ, внутри И; условие =
     аргумент 1, оператор, аргумент 2; аргумент — константа / индикатор (из
     каталога U3: имя, таймфрейм, период/метод/серия/сдвиг/параметры по флагам
     каталога) / свеча (серия, таймфрейм, сдвиг); добавление/удаление групп и
     условий;
  3. **Ордера (сетка)**: режим «Простой» / «Свой» / «Сигнал»; поля по режиму;
     для «Своего» — таблица уровней (`CustomLevelsEditor`), для «Сигнала» —
     сигнальные группы тем же редактором фильтров;
  4. **Тейк-профит**: вид из схемы (`fixed_percentage`, `multi_take`, `signal`,
     `trailing`) с полями своего вида (включая `breakeven` для multi_take);
  5. **Стоп-лосс**: простой (`percent` + `stop_bot_after` — переключатель
     «да/нет/— не выбрано —», **без значения по умолчанию**) и сигнальный
     (`signal_stop`: группы, опорная цена, минимальное смещение);
  6. **Риск**: `risk.emergency_stop` (чекбокс, default `false` из схемы),
     `max_position_size`, `max_concurrent_bots`, `daily_loss_limit` (пустые).
- Главное правило формы (не придумывать значения) реализовано в
  `frontend/src/lib/schema.ts`: `initialValue` берёт только `default` из JSON
  Schema; поля Python-`default_factory` (в схему не попадают) остаются пустыми;
  `compact` при сохранении убирает только `undefined`, `null` сохраняется как
  «не выбрано» (для `stop_bot_after` `null` не превращается в `false`).
- Подсказки: `description`/`title` из схемы, для `exit.stop_loss.percent` — по
  E1: «Процент сверх перекрытия сетки от цены первого ордера».
- **Проверка**: перед сохранением `POST /api/strategies/validate`; ошибки 422
  раскладываются к полям (`api.ts::fieldErrors` — `body.exit.take_profit.percent`
  → поле); результат проверки живой торговли — плашка «Для живой торговли
  подходит» / «Только бэктест: <причина>` (дословно из ответа).
- Переключатель «JSON»: текст и форма синхронны; невалидный JSON не
  сохраняется (показывается ошибка парсинга).
- Незнакомые поля схемы (не входят в блоки) рендерятся общим рендером по типу
  (`UnknownFields`/`GenericField`) и **не теряются** при сохранении.

### U5. Боты

- Список: название, статус цветом, счёт, инструмент, депозит, стратегия версия;
  `last_error`, `last_skip_reason`, `stop_reason`; переход на страницу бота.
- Создание: стратегия → версия; счёт (только сохранённые локально — фильтр
  `id != null` из `GET /api/accounts`, признак «сохранён» показывается в списке
  счетов, «Синхронизировать счета» — на странице песочницы/счетов); инструмент
  (выбор из `GET /api/instruments` по тикеру/названию); депозит — пустое поле.
- Действия: старт (в боевом режиме — подтверждение, U2), стоп, экстренная
  остановка (подтверждение), изменение депозита и смена версии стратегии —
  `PATCH /api/bots/{id}` (доступно со страницы бота), удаление (подтверждение,
  только STOPPED/без открытой сделки — кнопка активна по статусу, при 409
  ответ показывается дословно).
- Страница бота (`/bots/:id`): текущая сделка `GET /api/bots/{id}/deal` —
  статус, направление, опорная цена (P0), средняя цена, позиция; таблица
  уровней (№, сторона, цена, номинал, кол-во, смещение %, статус, исполнено,
  заявка); TP (цена, объём, %); стоп (цена, объём, % активен ли); история
  сделок с причиной закрытия (take_profit → «Тейк-профит», stop_loss →
  «Стоп-лосс» и т.д.).
- Обновление опросом: интервал — настройка фронтенда (ops-параметр): ключ
  localStorage `veles.ui.poll_interval_ms` (`frontend/src/lib/settings.ts`),
  по умолчанию **5000 мс**, переключатель на странице ботов (выкл/5/10/30 с).
  Описан здесь; в UI — селектор «Автообновление».

### U6. Бэктест

- Ввод: стратегия и версия **или** инлайн-конфигурация (JSON, общей формой из
  U4 правила — конфигурация целиком, без предзаполнения); инструмент;
  таймфрейм **подставляется из конфигурации и не редактируется** (B3; если в
  конфигурации таймфрейм не задан — селектор, т.к. backend не проверяет);
  период (пустые по умолчанию поля дат-времени); депозит, maker/taker-комиссия,
  проскальзывание — **пустые обязательные** поля (без предзаполнения).
- Результат: сводка (начальный/итоговый капитал, чистая PnL, ROI, число сделок,
  прибыльные/убыточные, win rate, средняя сделка, средняя длительность, макс.
  просадка, комиссии); таблица сделок (вход/выход, цены, объём, чистая PnL,
  причина); график свечей за период с отметками входов и выходов —
  `CandleChart` (`frontend/src/components/CandleChart.tsx`, переписан на OHLC;
  отметки входа — жёлтые, выхода — голубые; привязка к свече — по времени с
  допуском до 1 часа).
- Ошибки 422 (предел свечей, несовпадение таймфрейма, нет лота/шага цены)
  показываются дословно рядом с формой.

### U7. Песочница и счета

- Статус T-Invest и режим (U2) — в шапке и на странице.
- Счета брокера с признаком «сохранён»; кнопка «Синхронизировать счета»
  (`POST /api/accounts/sync`); кнопка «Синхронизировать инструменты» — на
  «Обзоре» (`POST /api/instruments/sync`).
- Песочница: открыть счёт (`POST /api/sandbox/accounts`), пополнить (сумма и
  валюта — пустые обязательные поля), закрыть (с подтверждением).
- Предупреждения (факты MVP-7.0): стоп-заявок в песочнице нет — бота со
  стоп-лоссом там не запустить (выводится текст про поддержку стоп-заявок у
  боевого счёта); неисполненные заявки песочница удаляет после окончания
  торговой сессии. Если `sandbox=false` — блок песочницы скрыт, показывается
  пояснение (операции вернут 409, текст дословно).

### U8. Проверка в браузере

- `vitest` добавлен (`frontend/package.json`: `"test": "vitest run"`,
  `vite.config.ts` — `test: { environment: "node" }`).
- Тесты — `frontend/src/lib/form.test.ts` (**5 кейсов**):
  1. схема → начальное состояние формы: значения только из `default` схемы,
     обязательные поля без `default` пустые (в т.ч. `entry.method`, `dca.mode`);
  2. форма → конфигурация → форма без потерь (незнакомые поля, `null`, `false`
     сохраняются; удаляется только `undefined`);
  3. ошибки 422 с путями попадают к нужным полям (`fieldErrors`), строковый
     `detail` дословно;
  4. `stop_bot_after` не выбран по умолчанию (`undefined`), пустой выбор не
     превращается в `false` (`compact({stop_bot_after: null})` → `null`,
     `undefined` → отсутствует);
  5. (в составе п.3) дословность `verbatimMessage`.
- **e2e (Playwright) и скриншоты — НЕ делались.** Причина: пакет `playwright` в
  проекте не установлен (в `frontend/node_modules` его нет; браузеры в кэше
  `ms-playwright` есть, но без пакета не воспроизвести подходящую версию), а
  запуск полного стека (PostgreSQL + alembic + uvicorn + T-Invest токен) в этой
  среде недоступен — контракт допускает отказ с объяснением. Ручной прогон:
  `docker compose up`, `alembic upgrade head`, `uvicorn app.main:app`,
  `npm run dev` в `frontend/`.

## Таблица терминов (U1)

Источник: «Veles Help Center — engineering reference.md» (термины из справки
Veles) / «Перевод проекта» (термины без документированного Veles-соответствия).
Таблица реализована как `TERMS` в `frontend/src/lib/labels.ts`.

| Поле конфигурации | Подпись в интерфейсе | Источник термина |
|---|---|---|
| name | Название | Перевод проекта |
| direction | Направление | Veles: Direction: Long or Short |
| timeframe | Таймфрейм | Veles: timeframe/interface |
| lookback_bars | История, баров | Перевод проекта |
| entry | Условия входа | Veles: Entry conditions |
| entry.method | Метод расчёта | Veles: At bar close / Once per minute |
| entry.groups | Группы фильтров | Veles: Multiple filters; groups AND/OR |
| arg1 / arg2 | Аргумент | Veles: Argument 1 + Operator + Argument 2 |
| operator | Оператор | Veles: > < crossing operators |
| argument: constant | Константа | Veles: constants |
| argument: indicator | Индикатор | Veles: Flexible indicators |
| argument: candle | Свеча | Veles: Candle: Open/Close/High/Low/Volume + shift |
| indicator.shift | Сдвиг (баров) | Veles: shift |
| dca_grid | Ордера (сетка) | Veles: DCA/grid |
| dca_grid.mode | Режим | Veles: Trading mode: Simple / Custom / Signal |
| dca_grid.levels | Уровней | Veles: Grid order count |
| dca_grid.overlap_percent | Перекрытие (%) | Veles: Price-change overlap |
| dca_grid.spacing_percent | Шаг (%) | Veles: overlap/spacing |
| dca_grid.martingale_percent | Мартингейл (%) | Veles: Martingale percentage |
| dca_grid.logarithmic_factor | Логарифм. коэффициент | Veles: Logarithmic price distribution |
| dca_grid.first_order_offset_percent | Смещение 1-го ордера (%) | Veles: First-order offset |
| dca_grid.pull_up_percent | Подтяжка сетки (%) | Veles: Grid pull-up / refresh |
| dca_grid.active_limit | Лимит активных заявок | Veles: orders visible in advance |
| dca_grid.custom_levels | Уровни сетки | Veles: custom grid |
| dca_grid.signal_groups | Сигнальные группы | Veles: Signal mode |
| exit | Тейк-профит и выход | Veles: Take-profit mode |
| exit.take_profit | Тейк-профит | Veles: Take-profit mode: Simple / Custom / Signal |
| take_profit: fixed_percentage | Фиксированный процент | Veles: fixed profit |
| take_profit: multi_take | Несколько частичных | Veles: multiple partial exits |
| take_profit: signal | Сигнальный | Veles: indicators/signals exits |
| take_profit: trailing | Трейлинг | Перевод проекта |
| exit.stop_loss | Стоп-лосс | Veles: Stop-loss |
| exit.stop_loss.percent | Процент стопа | Veles (E1): сверх перекрытия сетки от цены первого ордера |
| exit.stop_loss.stop_bot_after | Остановить бота после стопа | Veles: Stop bot after N deals |
| exit.signal_stop | Сигнальный стоп-лосс | Veles: Stop-loss (signal) |
| risk | Риск | Veles: Risk management principles |
| risk.max_position_size | Макс. размер позиции | Перевод проекта |
| risk.max_concurrent_bots | Макс. одновременных ботов | Перевод проекта |
| risk.daily_loss_limit | Дневной лимит убытка | Перевод проекта |
| risk.emergency_stop | Экстренная остановка | Veles: emergency stop / safety controls |

## Каталог индикаторов (U3)

`GET /api/strategies/indicators` → список `IndicatorResponse`:
имя, `series`, параметры (`name`/`type`/`required`), флаги использования
`period`/`method`/`series`/`params`. Источник — единый `INDICATOR_CATALOG` в
`backend/app/strategies/indicators.py`, из которого работает и `indicator_series`
(расчёт). Значения по умолчанию (например, `period=14` у RSI) в каталог **не
вынесены** — только описание параметра.

## Отклонение (флаг для ревью)

**Вне рамки «backend меняется только в U2 и U3» добавлено одно поле:**
`id: int | None` в `InstrumentResponse` (`backend/app/schemas/invest.py` +
конвертер `backend/app/api/tinvest.py::_instrument_to_schema`).

Причина: `POST /api/bots` и `POST /api/backtests` принимают `instrument_id`
(локальный первичный ключ таблицы `instruments`), но `GET /api/instruments`
(и любой другой эндпоинт) локальный `id` не отдавал — только FIGI/тикер.
Интерфейс физически не мог передать `instrument_id` ни при создании бота, ни
при запуске бэктеста (U5/U6). Это выглядит как пробел API MVP-7.0 (R1–R8), а
не как семантическое изменение: поле **только добавляется** в ответ
(неразрывно), на чтение, у всех локальных инструментов заполнено.

Проверить: после `POST /api/instruments/sync` каждая запись `GET /api/instruments`
содержит числовой `id`, совпадающий с `instruments.id` в БД; бот и бэктест
принимают этот `id` (тесты `test_mvp70_api.py` не затронуты — они не сравнивают
полный состав ответа).

Если ревью не примет это — вариант «остаться на границе»: создать бота/запустить
бэктест через Swagger нельзя, U5/U6 остаются частично неработоспособными
(список ботов, страница сделки, конфигурация формы бэктеста — работают).

## Проверки

| Проверка | Результат |
|---|---|
| `pytest` (backend, venv) | **566 passed, 1 skipped** |
| `ruff check app tests scripts` | **All checks passed** |
| `alembic heads` | `0006_stop_loss (head)` — один head |
| `npm test` (vitest) | **5 passed** (1 файл) |
| `npm run build` (tsc --noEmit + vite build) | **OK** (248 KB gzip 75 KB) |
| diff от merge-base | см. ветку; изменений вне задачи не обнаружено |

## Известные ограничения

- e2e/скриншоты не выполнены (см. U8).
- Форма не копирует «коробочные» сценарии Veles (загрузка готовых конфигураций,
  предзаполнение периодов) — по контракту ничего не придумывается.
- `instrument_id` в форме стратегии — простое числовое поле (глобального
  справочника инструментов в форме нет; выбор инструмента есть в создании бота,
  бэктесте и Обзоре).
- Мобильная вёрстка минимальна (контракт допускает десктоп).
- Авторизация отсутствует (вне задачи, как в MVP-5/6/7.0).
- Смена версии стратегии бота и изменение депозита доступны со страницы бота
  (R5); кнопки активируются по статусу (STOPPED и нет открытой сделки).

## Соответствие AGENTS.md

- Ветка/задача: `agent/review/mvp-7.1` от `master @ 795f4ed`, `master` не изменялся.
- Veles-семантика не менялась: фикстуры, формулы, дефолты индикаторов,
  DCA/TP/SL/сигнальная семантика, стоп-заявки (их отсутствие в песочнице
  сохранено и показано в UI); новых контрактов не введено (см. «Отклонение»).
- Финансовые значения в UI не предзаполняются; комиссии/депозит/суммы
  пополнения — пустые обязательные поля.
- Брокер-нейтральность: интерфейс не знает типов T-Invest (все подписи — по
  Veles/переводу проекта; стороны «Покупка/Продажа» — по OrderSide из API).

## Публикация

```
git push origin agent/review/mvp-7.1    # 7d662be (pushed, in sync with origin)
git push origin agent/control
git ls-remote origin agent/review/mvp-7.1 agent/control
```

Подтверждение `git ls-remote` (2026-10-05):

```
8df8f0f9dfe246ae46ed350a33108cd4b4e0eabb	refs/heads/agent/control
7d662be4f8a40ac8dd9347ba7c6163a3a3507efa	refs/heads/agent/review/mvp-7.1
```

Оба SHA совпадают с локальными (`agent/review/mvp-7.1` = `7d662be` —
реализация, `agent/control` = `8df8f0f` — этот отчёт).
