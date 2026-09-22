"""Opt-in live T-Invest sandbox integration test (MVP-6.2.1).

This test requires real T-Invest credentials (a token) and network access. It is
opt-in via the ``integration`` marker and is SKIPPED when no sandbox token is
configured, so it never runs in the ordinary ``pytest`` run and never fakes a
pass.

To run it against the sandbox (no real money):

    VELES_TINVEST_TOKEN=<sandbox token> VELES_TINVEST_SANDBOX=true \
        pytest -m integration -s tests/test_tinvest_stream_integration.py
"""

from __future__ import annotations

import asyncio

import pytest

from app.brokers.tinvest_stream_transport import (
    TInvestWebSocketStreamTransport,
    ws_url_from_base_url,
)
from app.core.config import get_settings

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not (get_settings().tinvest_token and get_settings().tinvest_sandbox),
    reason="T-Invest sandbox credentials are not configured",
)
async def test_sandbox_stream_subscribes_when_configured() -> None:
    """Open a real sandbox stream and verify frames are produced.

    Only runs when a sandbox token is configured; otherwise it is skipped.
    """
    settings = get_settings()
    url = settings.tinvest_stream_url or ws_url_from_base_url(settings.tinvest_base_url)
    transport = TInvestWebSocketStreamTransport(url=url, token=settings.tinvest_token)

    async def _run() -> None:
        await transport.connect(["sandbox-account"])
        count = 0
        async for _message in transport.messages():
            count += 1
            if count >= 3:
                break

    await asyncio.wait_for(_run(), timeout=30)
