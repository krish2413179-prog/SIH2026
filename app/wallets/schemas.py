"""Pydantic v2 schemas for wallet address submission.

Covers the request/response contract for:
  POST /cases/{case_id}/wallets  — batch wallet submission

Requirements: 3.2, 3.3, 3.5
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator, model_validator

from app.wallets.validators import SUPPORTED_CHAINS, validate_for_chain


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class WalletSubmitItem(BaseModel):
    """A single wallet address submission within a batch request.

    *chain* is an optional override.  When provided it must be one of the
    Supported Chains and the address must pass that chain's format validator.
    When omitted the Engine auto-detects applicable chains.

    Requirements: 3.2, 3.3
    """

    address: str = Field(
        ...,
        min_length=1,
        description="Cryptocurrency wallet address to investigate",
    )
    chain: str | None = Field(
        None,
        description=(
            "Optional chain override (BTC, ETH, TRX, BSC, SOL, MATIC). "
            "When supplied the address is validated against this chain only."
        ),
    )

    @field_validator("chain", mode="before")
    @classmethod
    def normalise_chain(cls, v: str | None) -> str | None:
        """Uppercase the chain identifier and reject unknown values."""
        if v is None:
            return None
        upper = v.upper()
        if upper not in SUPPORTED_CHAINS:
            raise ValueError(
                f"Unsupported chain {v!r}. Must be one of: {', '.join(SUPPORTED_CHAINS)}"
            )
        return upper

    @model_validator(mode="after")
    def address_matches_chain(self) -> "WalletSubmitItem":
        """When *chain* is supplied, validate *address* against it.

        If validation fails at the item level we surface a descriptive error
        so the batch endpoint can collect per-item failures.

        Requirements: 3.2, 3.3
        """
        if self.chain is not None and not validate_for_chain(self.address, self.chain):
            raise ValueError(
                f"Address {self.address!r} does not match the expected format "
                f"for chain {self.chain}."
            )
        return self


class WalletSubmitBatch(BaseModel):
    """Batch wallet submission payload — up to 50 addresses per request.

    Items beyond 50 cause a 400 validation error before any processing
    begins (Req 3.5).
    """

    addresses: list[WalletSubmitItem] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of wallet address items (1–50 per request)",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class WalletSubmitResult(BaseModel):
    """Per-item result returned in the batch submission response.

    *trace_id* is None when the submission triggered deduplication return
    before a trace job was queued (unexpected edge case) or when the address
    matched multiple chains and individual trace IDs are tracked per chain.

    *is_duplicate* — True when an existing trace within the last 24 hours
    was found and its ID was returned instead of enqueueing a new job
    (Req 3.6).
    """

    model_config = {"from_attributes": True}

    address: str = Field(..., description="The submitted wallet address")
    chain: str = Field(..., description="Resolved chain identifier")
    trace_id: uuid.UUID | None = Field(
        None,
        description="Trace job UUID (None if not yet queued)",
    )
    is_duplicate: bool = Field(
        False,
        description="True when an existing active trace was returned (Req 3.6)",
    )


class WalletSubmitResponse(BaseModel):
    """Response envelope for POST /cases/{case_id}/wallets.

    *results* contains one entry per successfully processed (address, chain)
    pair — a single address matching multiple chains produces multiple result
    entries.

    *errors* holds per-item failure dicts for addresses that could not be
    processed; each entry contains at minimum ``{"address": …, "detail": …}``.
    """

    results: list[WalletSubmitResult] = Field(
        default_factory=list,
        description="Successfully processed (address, chain) pairs",
    )
    errors: list[dict] = Field(
        default_factory=list,
        description="Per-item failures with address and error detail",
    )
