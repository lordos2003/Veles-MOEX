# REPORT-MVP-7.6 — «Данные доступны с»: дата начала истории бумаги, «Весь период», фильтр пресетов

## Статус

**Реализация завершена, готово к ревью (раунд 1).**

- Ветка реализации: `agent/review/mvp-7.6` (от `origin/master @ c5903a6`)
  - **`9904b33`** — H2, H3, H4, U12, F1 + тесты — **pushed, in sync with origin**
    (проверено `git ls-remote origin agent/review/mvp-7.6 agent/control`).
- База: `origin/master @ c5903a6` (после публикации MVP-7.5). `master` не изменялся.
- Отчёт: `agent/control:.agent/REPORT-MVP-7.6.md` — pushed вместе со
  скриншотами; финальный HEAD `agent/control` — см. «Публикация» (ls-remote).
- Самостоятельная приёмка не объявлялась — ревью за независимым ревьюером.

## H2. Хранение и синхронизация

- Миграция `backend/alembic/versions/0007_first_candle_dates.py`: в `instruments`
  добавлены `first_1min_candle_date`, `first_1day_candle_date`
  (`DateTime(timezone=True)`, nullable); `down_revision = "0006_stop_loss"`,
  `alembic heads` — единственная голова `0007_first_candle_dates (head)`.
  Имя ревизии — `0007_first_candle_dates` (23 символа): исходное
  `0007_instrument_first_candle_dates` (34 символа) не прошло
  `test_alembic_revision_ids_fit_version_column` (`alembic_version.version_num` —
  `varchar(32)`), переименовано.
- **Специфика контракта T-Invest (найдено при живом прогоне):** REST-шлюз
  T-Invest сериализует поля прото-контракта `instruments.proto` (56/57) в
  **camelCase** — `first1minCandleDate`, `first1dayCandleDate`, а не в
  snake_case. Первая реализация читала `first_1min_candle_date` → живая
  синхронизация дала все `NULL`; после исправления маппинга на camelCase
  (проверено против реального ответа песочницы) поля заполнились. Фикстура
  теста адаптера обновлена на camelCase с комментарием «verified against the
  live sandbox response».
- `TInvestAdapter._to_instrument`: `first_1min_candle_date` /
  `first_1day_candle_date` → `BrokerInstrument` (типы T-Invest остаются только
  в адаптере, брокер-нейтральность не нарушена). Отсутствует/пустое значение →
  `None` — ничего не подставляется.
- `app/services/instruments.py` (`upsert_from_broker`): оба поля сохраняются
  при «Синхронизировать инструменты»; повторная синхронизация обновляет.
  Старые строки остаются `NULL` до следующей синхронизации.

## H3. API

- `GET /api/instruments` (`InstrumentResponse`) отдаёт `first_1min_candle_date`
  и `first_1day_candle_date` — UTC, RFC3339/ISO (`_to_iso_utc`, суффикс `Z`).
  Другие контракты API не менялись.

## H4. Какая дата для какого таймфрейма (проектное решение, утверждено владельцем 2026-10-08)

Реализовано буквально в `frontend/src/pages/BacktestPage.tsx`:

- 1m, 5m, 15m, 30m, 1h, 4h → `first_1min_candle_date`;
- 1d, 1w, 1mo → `first_1day_candle_date`;
- дата `NULL` → «источника нет»: поведение как в MVP-7.5 («Весь период»
  отключён, пресеты не фильтруются, подсказка «нет данных о доступном
  диапазоне»). Пересчёт/эвристики не вводились.

## U12. «Бэктест»

- Подсказка под полем «Период»: **«Данные для бэктеста доступны с: ДД.ММ.ГГГГ»**
  (дата — в часовом поясе браузера, граница по дате; меняются бумага/таймфрейм —
  подсказка обновляется).
- «Весь период»: от earliest (по H4) до текущего момента; включён только при
  известной дате.
- Пресеты («Год», «3 года», …) видимы, только если их начало не раньше earliest;
  у молодой бумаги лишние пресеты исчезают. Дни календаря до earliest неактивны.
- `PeriodPicker` уже принимал `earliestAvailable` — подключён
  (`earliestAvailable` в формате `YYYY-MM-DD`, из `toLocalDateKey`).
- Таймфрейм берётся из выбранной стратегии/формы бэктеста; не выбран —
  как «источника нет» (подсказка о недоступности, пресеты не фильтруются).

## F1. Хвост из MVP-7.5 (M1)

- `lookback_bars: null` убран из JSON-шаблона формы и из тел
  `POST/PUT /api/strategies`: если поле пользователем не задано, ключа в теле
  нет (причина появления `null` — Pydantic v2 эмитит `default: null` рядом с
  `$ref`, `initialValue` это подхватывал; ключ удаляется).
- Явное значение `lookback_bars` в старых стратегиях сохраняется как есть.

## Тесты

1. `backend/tests/test_tinvest_adapter.py`: маппинг camelCase-полей (есть/нет
   значения) → DTO.
2. `backend/tests/test_instrument_service.py`: синхронизация сохраняет поля;
   повторная обновляет; нет значения → `NULL`.
3. `backend/tests/test_tinvest_api.py`: `GET /api/instruments` отдаёт поля.
4. `frontend/src/pages/BacktestPage.test.tsx`: сопоставление H4, «Весь период» =
   earliest → now, фильтр пресетов, `NULL` → поведение MVP-7.5, подсказка
   меняется при смене бумаги/таймфрейма.
5. `frontend/src/pages/StrategyFormPage.test.tsx`: F1 — форма не добавляет
   `lookback_bars`; JSON-режим его не показывает; старая стратегия с
   `lookback_bars` сохраняет значение.

## Живой прогон (критерии приёмки задачи)

Чистая копия: `docker compose down -v` → `up -d --build` (postgres, redis,
backend — `alembic upgrade head`, frontend), ключ песочницы владельца из
веб-интерфейса проекта на backend; токен/ключи в REPORТ/коммиты не попадали.

- «Синхронизировать инструменты» → **270** инструментов MOEX.
- `instruments`: `first_1min_candle_date` заполнена у **269 из 270**,
  `first_1day_candle_date` — у **269 из 270**; у одной бумаги (**DIOD**) обе
  даты `NULL` — так и оставлено, ничего не подставлено.
- Значения (из БД `GET /api/instruments`):
  - **SBER** (BBG004730N88): `first_1min_candle_date = 2018-03-07T18:33:00Z`,
    `first_1day_candle_date = 2000-01-04T07:00:00Z`;
  - **GAZP** (BBG004730RP0): `first_1min_candle_date = 2018-03-07T18:33:00Z`,
    `first_1day_candle_date = 2006-01-23T07:00:00Z`;
  - **DIOD** (BBG000R0L782): обе `NULL`.
- Календарь «Бэктест» (браузер, live):
  - SBER, таймфрейм 1d → подсказка **«Данные для бэктеста доступны с: 04.01.2000»**,
    «Весь период» включён, пресеты «Год»/«3 года» присутствуют (история > 3 лет).
  - DIOD → подсказка «нет данных о доступном диапазоне», «Весь период»
    отключён, пресеты не фильтруются (поведение MVP-7.5).

Скриншоты (в `agent/control:.agent/screenshots/MVP-7.6/`):
- `sber-1d-hint.png` — подсказка «доступны с: 04.01.2000»;
- `sber-1d-calendar.png` — календарь: «Весь период», пресеты;
- `diod-null-hint.png` — DIOD: источника нет, «Весь период» отключён.

## Изменённые/новые файлы

`backend/app/brokers/base.py`, `backend/app/brokers/tinvest.py`,
`backend/app/models/instrument.py`, `backend/app/services/instruments.py`,
`backend/app/schemas/invest.py`, `backend/app/api/tinvest.py`,
`backend/alembic/versions/0007_first_candle_dates.py` (нов.),
`backend/tests/test_tinvest_adapter.py`, `backend/tests/test_instrument_service.py`,
`backend/tests/test_tinvest_api.py`, `frontend/src/types.ts`,
`frontend/src/pages/BacktestPage.tsx`, `frontend/src/pages/BacktestPage.test.tsx`,
`frontend/src/pages/StrategyFormPage.tsx`, `frontend/src/pages/StrategyFormPage.test.tsx`.

## Валидация

- `pytest` (backend): **607 passed, 1 skipped** (пропуск — существующий
  `test_tinvest_stream_integration.py`, SkipIf — требуется живой поток брокера).
- `ruff check app tests scripts` (backend): **All checks passed!**
- `alembic heads`: `0007_first_candle_dates (head)` — единственная голова.
- `npm test` (frontend): **71 passed** (11 файлов).
- `npm run build` (frontend): `tsc --noEmit` + `vite build` — успешно.
- Дифф просмотрен от `git merge-base master@origin`; новых Veles-семантик не
  вводилось; H4 — проектное решение владельца, описано выше.

## Ограничения

1. T-Invest отдаёт `first_1min_candle_date` одинаковой (2018-03-07) для всех
   бумаг MOEX в песочнице — это значение брокера, не подменялось.
2. Для DIOD брокер дат не дал (`NULL`) — поведение «источника нет» (MVP-7.5),
   ничего не подставлено.
3. H4 — проектное решение (см. раздел), не контракт документации T-Invest.
4. Живой поток (stream-интеграция) в этой среде не проверялся — существующий
   SkipIf-тест (к задаче отношения не имеет).

## Публикация

```
git push origin agent/review/mvp-7.6   # 9904b33 (проверено git ls-remote)
git push origin agent/control          # HEAD = коммит этого отчёта (со скриншотами)
```

Проверено `git ls-remote origin agent/review/mvp-7.6 agent/control`: remote SHAs
равны локальным. `master` не изменялся, force/rebase не применялись.

PR `agent/review/mvp-7.6` → `master` открыт после push (см. отдельное
сообщение/комментарий).
