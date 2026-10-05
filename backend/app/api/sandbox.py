"""T-Invest sandbox REST endpoints (MVP-7.0 R3).

Sandbox endpoints operate on the T-Invest test environment only: they return
HTTP 409 when ``TINVEST_SANDBOX=false``. All T-Invest specifics stay inside
``TInvestAdapter``; the API layer only sees broker-agnostic results.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_broker_adapter, get_settings_dep
from app.brokers import BrokerAdapter, SandboxUnsupportedError
from app.core.config import Settings
from app.schemas.sandbox import (
    SandboxAccountResponse,
    SandboxPayInRequest,
    SandboxPayInResponse,
)

router = APIRouter(tags=["sandbox"])


def _require_sandbox(settings: Settings) -> None:
    """Reject sandbox operations when the sandbox is disabled (HTTP 409)."""
    if not settings.tinvest_sandbox:
        raise SandboxUnsupportedError(
            "sandbox is disabled: set TINVEST_SANDBOX=true to use sandbox endpoints"
        )


@router.post("/sandbox/accounts", response_model=SandboxAccountResponse)
async def open_sandbox_account(
    broker: Annotated[BrokerAdapter, Depends(get_broker_adapter)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SandboxAccountResponse:
    """Open a virtual sandbox account at T-Invest (no real money)."""
    _require_sandbox(settings)
    account_id = await broker.open_sandbox_account()
    return SandboxAccountResponse(account_id=account_id)


@router.post("/sandbox/accounts/{account_id}/pay-in", response_model=SandboxPayInResponse)
async def sandbox_pay_in(
    account_id: str,
    payload: SandboxPayInRequest,
    broker: Annotated[BrokerAdapter, Depends(get_broker_adapter)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SandboxPayInResponse:
    """Deposit paper money into a sandbox account (amount + currency required)."""
    if payload.account_id != account_id:
        raise SandboxUnsupportedError("path and body account_id do not match")
    _require_sandbox(settings)
    balance = await broker.sandbox_pay_in(payload.account_id, payload.amount, payload.currency)
    return SandboxPayInResponse(account_id=payload.account_id, balance=balance)


@router.delete("/sandbox/accounts/{account_id}", response_model=SandboxAccountResponse)
async def close_sandbox_account(
    account_id: str,
    broker: Annotated[BrokerAdapter, Depends(get_broker_adapter)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SandboxAccountResponse:
    """Close a virtual sandbox account."""
    _require_sandbox(settings)
    await broker.close_sandbox_account(account_id)
    return SandboxAccountResponse(account_id=account_id)
