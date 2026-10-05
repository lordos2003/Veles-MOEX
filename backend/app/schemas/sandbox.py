"""Pydantic schemas for the T-Invest sandbox REST API."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class SandboxAccountResponse(BaseModel):
    """A sandbox account opened in the T-Invest test environment."""

    account_id: str


class SandboxPayInRequest(BaseModel):
    """Paper money deposit to a sandbox account.

    ``amount`` and ``currency`` are mandatory: no default cash amount is
    invented by the platform.
    """

    account_id: str
    amount: Decimal = Field(gt=0, description="Amount of paper money to deposit")
    currency: str = Field(min_length=1, description="Currency code, e.g. 'rub'")


class SandboxPayInResponse(BaseModel):
    """Result of a sandbox pay-in: the resulting balance of the account."""

    account_id: str
    balance: Decimal
