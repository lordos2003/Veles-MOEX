"""Real T-Invest WebSocket stream transport (MVP-6.2.1) tests.

These are deterministic (no real network/token). They verify the WebSocket
transport's JSON handling, key normalization from the real camelCase API
contract to the broker-neutral message shape, and the end-to-end mapping of real
stream frames (NEW/PARTIALLYFILL/FILL/REJECTED/CANCELLED + trades) into
OrderManager/PositionManager events.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.brokers.tinvest_stream_transport import (
    TInvestWebSocketStreamTransport,
    normalize_json_keys,
    ws_url_from_base_url,
)
from app.brokers.tinvest_streams import TInvestStreamManager, _stream_status_to_state
from app.trading import OrderManager, OrderState, PositionManager
from tests.test_tinvest_streams import FakeStreamTransport, PlaceBroker, submit

FIGI = "BBG004730N88"


class FakeWsConn:
    """Minimal websockets connection stand-in for the transport."""

    def __init__(self, frames: list[str], sent: list[str] | None = None):
        self._frames = list(frames)
        self._sent = sent if sent is not None else []
        self.closed = False

    async def send(self, payload: str) -> None:
        self._sent.append(payload)

    async def recv(self):
        if self._frames:
            return self._frames.pop(0)
        await asyncio.sleep(60)  # simulate a healthy idle connection

    async def close(self) -> None:
        self.closed = True


def _order_state_frame(
    status: str, *, order_id="broker-1", trades: list[dict] | None = None
) -> str:
    return json.dumps(
        {
            "orderState": {
                "orderId": order_id,
                "orderRequestId": "8f4b2e0a-1f3e-4c7b-9a11-6c4d2e0a53b1",
                "executionReportStatus": status,
                "lotsRequested": "2",
                "lotsExecuted": "2",
                "statusInfo": "CAUSE_CANCELLED_BY_CLIENT",
                "trades": trades or [],
            }
        }
    )


def _trade(trade_id="t1", quantity="10", price="100"):
    return {"tradeId": trade_id, "quantity": quantity, "price": {"units": price, "nano": 0}}


# --- key normalization / url derivation ---


def test_normalize_json_keys() -> None:
    raw = {
        "orderState": {
            "orderId": "broker-1",
            "executionReportStatus": "EXECUTION_REPORT_STATUS_FILL",
            "orderRequestId": "abc",
            "trades": [
                {
                    "tradeId": "t1",
                    "dateTime": "2025-01-01T10:00:00Z",
                    "price": {"units": "100", "nano": 0},
                }
            ],
        }
    }
    norm = normalize_json_keys(raw)
    assert "order_state" in norm
    assert norm["order_state"]["execution_report_status"] == "EXECUTION_REPORT_STATUS_FILL"
    assert norm["order_state"]["trades"][0]["trade_id"] == "t1"
    assert norm["order_state"]["trades"][0]["date_time"] == "2025-01-01T10:00:00Z"
    assert norm["order_state"]["trades"][0]["price"]["units"] == "100"


def test_ws_url_from_base_url() -> None:
    assert ws_url_from_base_url("https://invest-public-api.tbank.ru/rest") == (
        "wss://invest-public-api.tbank.ru/ws/"
    )
    assert ws_url_from_base_url("https://sandbox-invest-public-api.tbank.ru/rest") == (
        "wss://sandbox-invest-public-api.tbank.ru/ws/"
    )


async def test_transport_sends_subscription_request() -> None:
    sent: list[str] = []
    conn = FakeWsConn([], sent=sent)
    transport = TInvestWebSocketStreamTransport(url="wss://x/ws/", token="tok")
    with patch("websockets.connect", new=AsyncMock(return_value=conn)):
        await transport.connect(["acc-1"])
    assert len(sent) == 2
    body = json.loads(sent[0])
    assert body["accounts"] == ["acc-1"]
    assert body["pingDelayMs"] == 10000


async def test_transport_requires_token() -> None:
    transport = TInvestWebSocketStreamTransport(url="wss://x/ws/")
    with patch("websockets.connect", new=AsyncMock(return_value=FakeWsConn([]))):
        import pytest

        with pytest.raises(ValueError):
            await transport.connect(["acc-1"])


# --- real stream frame -> broker-neutral mapping ---


async def _consume_frames(frames: list[str]) -> list[dict]:
    transport = TInvestWebSocketStreamTransport(url="wss://x/ws/", token="tok")
    conn = FakeWsConn(frames)
    collected: list[dict] = []
    with patch("websockets.connect", new=AsyncMock(return_value=conn)):
        await transport.connect(["acc-1"])
        async for message in transport.messages():
            collected.append(message)
            if len(collected) >= len(frames):
                break
    return collected


async def test_real_statuses_map_to_internal_state() -> None:
    frames = [
        _order_state_frame("EXECUTION_REPORT_STATUS_NEW"),
        _order_state_frame("EXECUTION_REPORT_STATUS_PARTIALLYFILL"),
        _order_state_frame("EXECUTION_REPORT_STATUS_FILL"),
        _order_state_frame("EXECUTION_REPORT_STATUS_REJECTED"),
        _order_state_frame("EXECUTION_REPORT_STATUS_CANCELLED"),
    ]
    messages = await _consume_frames(frames)
    statuses = [m["order_state"]["execution_report_status"] for m in messages]
    assert statuses == [
        "EXECUTION_REPORT_STATUS_NEW",
        "EXECUTION_REPORT_STATUS_PARTIALLYFILL",
        "EXECUTION_REPORT_STATUS_FILL",
        "EXECUTION_REPORT_STATUS_REJECTED",
        "EXECUTION_REPORT_STATUS_CANCELLED",
    ]
    assert [_stream_status_to_state(s) for s in statuses] == [
        OrderState.SUBMITTED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.REJECTED,
        OrderState.CANCELLED,
    ]


async def test_real_frames_drive_partial_fill_and_dedup() -> None:
    # Two frames: PARTIALLYFILL with trade t1, then FILL with trades t1 (dedup) + t2.
    frames = [
        _order_state_frame(
            "EXECUTION_REPORT_STATUS_PARTIALLYFILL", trades=[_trade("t1", "10", "100")]
        ),
        _order_state_frame(
            "EXECUTION_REPORT_STATUS_FILL",
            trades=[_trade("t1", "10", "100"), _trade("t2", "10", "101")],
        ),
    ]
    messages = await _consume_frames(frames)

    om = OrderManager(PlaceBroker(), PositionManager())
    order = await submit(om, quantity="20")
    mgr = TInvestStreamManager(object(), FakeStreamTransport([]), om, "acc-1")

    for message in messages:
        await mgr._dispatch(message)

    assert order.filled_quantity == Decimal("20")
    assert order.status == OrderState.FILLED
    pos = om.positions().get(FIGI)
    assert pos is not None
    assert pos.quantity == Decimal("20")
    assert pos.average_price == Decimal("100.5")
