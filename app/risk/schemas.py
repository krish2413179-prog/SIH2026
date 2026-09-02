"""Pydantic v2 schemas for risk scoring and alert responses.

Requirements: 8.1, 8.2, 8.3, 8.4
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.risk.scorer import RiskBand


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class RiskScoreResult(BaseModel):
    """Risk score result returned from GET /traces/{trace_id}/risk.

    Captures the computed score, band classification, and identifying
    metadata for the wallet/trace that was evaluated.

    Requirements: 8.1, 8.2, 8.3
    """

    model_config = {"from_attributes": True}

    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Integer risk score in the range [0, 100]",
    )
    band: RiskBand = Field(
        ...,
        description="Risk band classification: low (0–39), medium (40–69), high (70–100)",
    )
    trace_id: uuid.UUID = Field(
        ...,
        description="UUID of the trace job that produced this score",
    )
    wallet_address: str = Field(
        ...,
        description="Wallet address that was scored",
    )
    computed_at: datetime = Field(
        ...,
        description="UTC timestamp when the score was computed",
    )


class RiskAlertResponse(BaseModel):
    """Representation of a high-risk alert record (score ≥ 70).

    Returned from dashboard alert listing and WebSocket push payloads.

    Requirement: 8.4
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID = Field(..., description="Alert record UUID")
    trace_id: uuid.UUID = Field(..., description="Trace that triggered this alert")
    case_id: uuid.UUID = Field(..., description="Parent case UUID")
    wallet_address: str = Field(..., description="Wallet address that triggered the alert")
    risk_score: int = Field(..., ge=70, le=100, description="Score at alert time (always ≥ 70)")
    risk_band: str = Field(..., description="Risk band at alert time — always 'high'")
    created_at: datetime = Field(..., description="UTC timestamp when the alert was created")
