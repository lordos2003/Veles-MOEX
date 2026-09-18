# Архитектура Veles-MOEX

## Схема потока

```
Browser (React/TS, Web UI)
   │   REST, WebSocket
   ▼
FastAPI (Python)
   │
   ▼
Strategy Engine │ Trading Engine │ Backtest Engine
   │                    │                │
   │                    └── Order Manager ── Position Manager ── Risk Manager
   ▼
BrokerAdapter (абстракция)
   │
   ├── TInvestAdapter ──→ T-Invest API ──→ MOEX      (Live)
   └── BacktestBroker                                 (Backtest, та же логика)
```

## Принципы

1. **Один движок.** Live и Backtest используют один и тот же
   Strategy/Trading Engine; отличаются только адаптеры исполнения
   (`TInvestAdapter` vs `BacktestBroker`).
2. **Изоляция брокера.** Strategy Engine не знает о T-Invest. Вся
   брокерская специфика — внутри слоя `BrokerAdapter`.
3. **Стратегия — это данные.** Стратегия описывается конфигурацией (например,
   условиями входа, сеткой DCA, типами тейк-профита), а не пользовательским
   Python-кодом.
4. **Версии стратегий неизменяемы.** `StrategyVersion` — отдельная сущность;
   исторический бэктест ссылается на конкретную версию, что обеспечивает
   воспроизводимость.
5. **Risk Manager над стратегией.** Стратегия не может обойти Risk Manager.

## Слои

| Слой | Ответственность |
|------|-----------------|
| Browser | Web UI, отображение, ввод стратегий |
| FastAPI | REST/WebSocket, валидация, маршрутизация |
| Strategy Engine | Оценка входа/выхода, сетка DCA — без отправки ордеров |
| Trading Engine | Оркестрация: Order/Position/Risk Managers |
| BrokerAdapter | Абстрактный контракт брокера |
| TInvestAdapter | Реализация для T-Invest (Live), заглушка |
| BacktestBroker | Реализация для исторических данных (Backtest) |
| PostgreSQL | Персистентность данных |
| Redis | Кэш/очередь/события |

## Замечания

- Прямое подключение к MOEX (ASTS/FIX/TWIME), Paper Trading, второй брокер и
  микросервисы — вне скоупа MVP (см. product specification, разделы 16–18).
- Реальные адаптеры и торговая механика реализуются в последующих заданиях;
  на данном этапе метод-заглушки поднимают `NotImplementedError`.
