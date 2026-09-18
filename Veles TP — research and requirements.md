# Veles TP — research and requirements for Veles-MOEX

Source: official Veles Help Center, article «Тейк-профит» (checked 2026-09-18).

## Veles exit modes

Veles documents three ways to close a trade:
1. Simple Take Profit — one limit order.
2. Multi-Takes / «Свой» — partial exits at multiple profit levels; with 2+ takes, break-even stop can be used.
3. Signal Take Profit / «Сигнал» — close on an indicator signal, with optional Minimum P&L.

## Simple TP

Profit is configured as a percentage from the average trade price. Veles places a limit order. After each averaging event, the old TP order is removed and a new order is created with updated price and volume.

## Multi-Take / «Свой»

Position is closed in parts at different profit levels. Each take has:
- Offset % — profit level from the average entry price;
- Volume % — portion of the position closed at that level.

After the first averaging event, Veles builds the take-profit order grid; subsequent orders are placed sequentially, and the grid is recalculated after further averaging.

With two or more takes, Veles supports a break-even stop. It can be configured relative to the average position price or relative to the previous take-profit level, with positive/zero/negative deviation. After the first take, the averaging grid is cancelled and the stop is maintained according to the selected rule. This stop is a profit-protection mechanism, not the ordinary loss-limiting stop.

## Signal TP / «Сигнал»

The trade closes automatically when the configured indicator/filter produces a signal. Veles also has Minimum P&L so that the position is not closed before the configured minimum profit; documented minimum is 0.1%.

Veles states that signal exit uses a market order. This differs from simple TP and Multi-Takes, which use limit orders.

## Trailing stop

Veles documents trailing stop as an additional mechanism in the simple TP context on supported crypto exchanges. For Veles-MOEX it should be treated as a separate feature and implemented only after verifying whether T-Invest/MOEX provides suitable order/trigger semantics.

## Veles-MOEX requirements

The Exit Engine must model TP types explicitly rather than as one generic percentage field:
- FixedPercentageTP
- MultiTakeTP
- SignalTP
- TrailingTP (future/conditional)

It must also model:
- average-price recalculation after DCA;
- partial fills and partial exits;
- cancellation/replacement of TP orders after averaging;
- interaction between DCA and TP;
- minimum P&L for signal exits;
- limit-vs-market execution semantics;
- commissions and slippage;
- position and remaining-volume accounting;
- break-even protection after Multi-Take.

Paper Trading is NOT an MVP requirement. Reconsider only if later testing shows it is needed.
