"""Pydantic schemas for the read-only runtime endpoint (MVP-7.1 U2)."""

from __future__ import annotations

from pydantic import BaseModel


class RuntimeResponse(BaseModel):
    """Read-only view of the application mode for the UI.

    All values come from the application settings; nothing here is derived
    from broker- or runtime-specific state. The UI uses this to show the
    sandbox/live mode and to gate bot actions (U2).
    """

    sandbox: bool
    live_trading_enabled: bool
    tinvest_configured: bool
