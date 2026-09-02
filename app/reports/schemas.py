"""Pydantic v2 models and JSON renderer for investigation reports.

Covers:
  - ReportModel — full report payload with all required sections (Req 11.1, 11.2, 11.3)
  - PydanticJSONRenderer — serialise ReportModel to bytes with embedded SHA-256
    content hash (Req 11.5)

Requirements: 11.1, 11.2, 11.3, 11.5
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class CaseMetadata(BaseModel):
    """Core metadata about the investigation case."""

    case_id: UUID
    title: str
    status: str


class WalletSummary(BaseModel):
    """Summary of a wallet address included in this trace."""

    address: str
    chain: str


class TraceSummary(BaseModel):
    """Aggregate statistics from the BFS trace traversal."""

    total_hops: int
    total_addresses: int
    total_transactions: int


class VASPAttribution(BaseModel):
    """A single VASP attribution result with confidence scoring."""

    vasp_name: str
    vasp_category: str
    confidence_score: float
    low_confidence: bool


class RiskAssessment(BaseModel):
    """Risk score and band classification for the traced wallet."""

    score: int
    band: str


class TypologyFinding(BaseModel):
    """A detected money-laundering typology pattern."""

    typology: str
    match_confidence: float


class TimelineEvent(BaseModel):
    """A single fund-flow event on the transaction timeline."""

    timestamp: datetime
    from_address: str
    to_address: str
    amount: float
    chain: str


class LowConfidenceAttribution(BaseModel):
    """Summary row for attributions flagged as low-confidence."""

    vasp_name: str
    confidence_score: float


# ---------------------------------------------------------------------------
# Root report model
# ---------------------------------------------------------------------------


class ReportModel(BaseModel):
    """Full investigation report payload.

    ``content_hash`` is computed by ``PydanticJSONRenderer`` before storage:
    the renderer serialises the model with ``content_hash=""`` to produce a
    deterministic byte string, computes SHA-256 over it, then re-serialises
    with the hash filled in.

    ``supervisor_signature`` format (set by the sign endpoint):
      {supervisor_user_id}:{iso_timestamp}:{content_hash}

    Requirements: 11.1, 11.2, 11.3, 11.5
    """

    report_id: UUID
    generated_at: datetime
    generated_by: str

    # Sections
    case_metadata: CaseMetadata
    wallets: list[WalletSummary]
    chains_analyzed: list[str]
    trace_summary: TraceSummary
    attributed_vasps: list[VASPAttribution]
    risk_assessment: RiskAssessment
    typologies: list[TypologyFinding]
    fund_flow_timeline: list[TimelineEvent]
    recommended_action: Literal["monitor", "disclose", "freeze"]

    # Optional / computed fields
    low_confidence_attributions: list[LowConfidenceAttribution] | None = None
    content_hash: str = ""
    supervisor_signature: str | None = None


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------


class PydanticJSONRenderer:
    """Serialise a ReportModel to JSON bytes with an embedded SHA-256 hash.

    Algorithm:
      1. Set ``content_hash=""`` and serialise to bytes (deterministic ordering
         via Pydantic's model_dump_json).
      2. Compute SHA-256 over those bytes.
      3. Re-serialise with ``content_hash`` filled in.
      4. Return the final bytes.

    The two-pass approach ensures the hash reflects the full payload without
    the hash field itself influencing its own digest.

    Requirement: 11.5
    """

    def render(self, report: ReportModel) -> bytes:
        """Render *report* to JSON bytes with an embedded content hash.

        Args:
            report: The fully populated ``ReportModel`` instance.

        Returns:
            UTF-8 encoded JSON bytes with ``content_hash`` embedded.
        """
        # Pass 1 — zero-out hash and serialise for digest input
        report_copy = report.model_copy(update={"content_hash": ""})
        payload_bytes: bytes = report_copy.model_dump_json().encode("utf-8")

        # Pass 2 — compute hash and re-serialise with it filled in
        digest = hashlib.sha256(payload_bytes).hexdigest()
        report_copy = report.model_copy(update={"content_hash": digest})
        final_bytes: bytes = report_copy.model_dump_json().encode("utf-8")

        return final_bytes
