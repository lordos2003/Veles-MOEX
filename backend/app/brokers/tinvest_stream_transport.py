"""Real T-Invest Open API stream transport (MVP-6.2.1).

The official T-Invest WebSocket service exposes the gRPC streaming methods
(OrderStateStream, TradesStream, PositionsStream, ...) over JSON WebSocket:

    wss://invest-public-api.tbank.ru/ws/

Authentication is via ``Authorization: Bearer <token>``. The JSON protocol is
selected with the ``Web-Socket-Protocol: json`` header (use ``json-proto`` to
get field names identical to the proto contracts). JSON can be sent in both
camelCase and snake_case.

This module implements the real |TInvestStreamTransport| over that WebSocket
service. It opens the connection, sends the subscription requests, decodes the
JSON frames into the broker-neutral ``dict`` message shape consumed by
|TInvestStreamManager|, and keeps the connection alive (server pings) while
surfacing timeouts / disconnects so the stream manager can reconnect.

No T-Invest types cross this boundary: only plain dictionaries are produced.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from urllib.parse import urlparse

from app.brokers.tinvest_streams import TInvestStreamTransport

logger = logging.getLogger(__name__)

_CAMEL_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE_2 = re.compile(r"([a-z0-9])([A-Z])")


def _to_snake_case(name: str) -> str:
    """Convert a camelCase JSON field name to snake_case."""
    value = _CAMEL_RE_1.sub(r"\1_\2", name)
    return _CAMEL_RE_2.sub(r"\1_\2", value).lower()


def normalize_json_keys(obj):
    """Recursively convert camelCase keys to snake_case in a parsed JSON object."""
    if isinstance(obj, dict):
        return {_to_snake_case(key): normalize_json_keys(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [normalize_json_keys(item) for item in obj]
    return obj


def ws_url_from_base_url(base_url: str) -> str:
    """Derive the WebSocket url from a REST base url (host is preserved).

    ``https://invest-public-api.tbank.ru/rest`` -> ``wss://invest-public-api.tbank.ru/ws/``
    """
    parsed = urlparse(base_url)
    return f"wss://{parsed.hostname}/ws/"


def build_stream_transport(url: str | None, token: str | None) -> TInvestWebSocketStreamTransport:
    """Build the real WebSocket transport from a stream url and token."""
    return TInvestWebSocketStreamTransport(url=url, token=token)


class TInvestWebSocketStreamTransport(TInvestStreamTransport):
    """Real T-Invest Open API WebSocket transport for order/trade streams.

    Connects to the WebSocket service, subscribes to OrderStateStream and
    TradesStream for the given accounts, and yields normalized (snake_case)
    message dicts. The server sends periodic ``ping`` frames; if no frame is
    received within ``receive_timeout`` seconds the connection is considered
    dead and an error is raised so the stream manager can reconnect.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        token: str | None = None,
        ping_delay_ms: int = 10_000,
        receive_timeout: float = 150.0,
    ) -> None:
        self._url = url
        self._token = token
        self._ping_delay_ms = ping_delay_ms
        self._receive_timeout = receive_timeout
        self._conn: object | None = None

    async def connect(self, accounts: list[str]) -> None:
        if not self._token:
            raise ValueError("T-Invest token is required to open the stream connection")
        if not self._url:
            raise ValueError("T-Invest stream url is required")
        import websockets  # local import: only needed for a real connection

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Web-Socket-Protocol": "json-proto",
        }
        conn = await websockets.connect(
            self._url, additional_headers=headers, open_timeout=10.0
        )
        self._conn = conn
        request = json.dumps({"accounts": list(accounts), "pingDelayMs": self._ping_delay_ms})
        # One subscription request per stream (order state + trades).
        await conn.send(request)
        await conn.send(request)

    async def messages(self) -> AsyncIterator[dict]:
        if self._conn is None:
            return
        conn = self._conn
        while True:
            try:
                frame = await asyncio.wait_for(conn.recv(), timeout=self._receive_timeout)
            except TimeoutError as exc:
                raise ConnectionError("T-Invest stream heartbeat timeout") from exc
            if isinstance(frame, bytes):
                frame = frame.decode("utf-8")
            try:
                message = json.loads(frame)
            except json.JSONDecodeError:
                logger.debug("ignoring non-JSON stream frame")
                continue
            yield normalize_json_keys(message)

    async def close(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                await conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("stream close error: %s", exc)
