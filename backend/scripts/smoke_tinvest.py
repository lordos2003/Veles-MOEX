"""Smoke test for the T-Invest read-only integration.

Read-only: authentication, accounts, instruments, market data, historical
candles. No orders, no trading.

Usage (PowerShell):
    $env:TINVEST_TOKEN="your_token"
    python -m scripts.smoke_tinvest

Requires the application code on the import path (run from the backend dir or
install the package).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.brokers import TInvestAdapter


async def main() -> None:
    adapter = TInvestAdapter()
    if not adapter.is_configured:
        print("TINVEST_TOKEN is not configured (set the env var first)")
        return

    print("auth: connecting...")
    await adapter.connect()
    print("auth: OK")

    accounts = await adapter.get_accounts()
    print(f"accounts: {len(accounts)}")
    for acc in accounts[:5]:
        print("  ", acc.account_id, "|", acc.name, "|", acc.status)

    if accounts:
        info = await adapter.get_account(accounts[0].account_id)
        print(
            f"account info: equity={info.equity} cash={info.available_cash} "
            f"currency={info.currency}"
        )

    instruments = await adapter.get_instruments("share")
    print(f"shares: {len(instruments)}")
    for inst in instruments[:5]:
        print("  ", inst.figi, "|", inst.ticker, "|", inst.name, "|", inst.currency)

    if instruments:
        figi = instruments[0].figi
        price = await adapter.get_last_price(figi)
        print(f"last price {figi}: {price.price}")
        now = datetime.now(UTC)
        candles = await adapter.get_candles(figi, "1d", now - timedelta(days=7), now, limit=5)
        print(f"candles {figi}: {len(candles)}")
        for candle in candles[:3]:
            print("  ", candle.time, "O", candle.open, "C", candle.close, "V", candle.volume)


if __name__ == "__main__":
    asyncio.run(main())
