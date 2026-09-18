# T-Invest read-only smoke test

Проверяет рабочую read-only интеграцию с T-Invest API без торговых операций:
authentication → accounts → instruments → market data → исторические свечи.

## Подготовка токена

Токен берётся только из переменной окружения `TINVEST_TOKEN`. **Никогда** не
передавайте его в аргументах командной строки, не пишите в код, README или Git.

## Запуск

```powershell
cd backend
$env:TINVEST_TOKEN="<ваш_токен>"
python -m scripts.smoke_tinvest
```

После запуска снимите переменную окружения:

```powershell
Remove-Item env:TINVEST_TOKEN
```

Или задайте её через `.env` (файл игнорируется Git) — тогда тот же скрипт
подхватит её через `pydantic-settings`.

## Что проверяется

- `connect()` — авторизация (получение списка счетов).
- `get_accounts()` / `get_account()` — счета и cash/equity.
- `get_instruments("share")` — список инструментов.
- `get_last_price(figi)` и `get_candles(...)` — рыночные данные и свечи.

## Ограничения

- Скрипт **read-only**: не выставляет заявки, не отменяет их, не торгует.
- Если токен отсутствует, скрипт завершается без запросов к API.
- При ошибке авторизации вернётся `AuthenticationError` (HTTP 401).
