"""Report generation and supervisor-signing service.

Implements:
  - generate_report — build a ReportModel from trace/case data, render to bytes,
                      persist as a Report ORM row, and write an audit entry.
  - sign_report     — supervisor approval: set supervisor_signature + status
                      and write an audit entry.

Requirements: 11.1, 11.2, 11.3, 11.5, 11.6, 11.7
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLogEntry
from app.cases.models import Case, CaseWallet, WalletAddress
from app.clustering.models import Attribution, Cluster as ClusterModel
from app.graph.models import TraceGraph, TraceJob
from app.reports.models import Report
from app.reports.pdf_renderer import WeasyPrintPDFRenderer
from app.reports.schemas import (
    CaseMetadata,
    LowConfidenceAttribution,
    PydanticJSONRenderer,
    ReportModel,
    RiskAssessment,
    TraceSummary,
    TimelineEvent,
    TypologyFinding,
    VASPAttribution,
    WalletSummary,
)
from app.typology.models import TypologyTag
from app.vasp_db.models import VASP


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _recommended_action(risk_score: int) -> str:
    """Map a risk score to a recommended action string.

    < 40  → monitor
    40–69 → disclose
    ≥ 70  → freeze

    Requirement 11.3
    """
    if risk_score < 40:
        return "monitor"
    if risk_score < 70:
        return "disclose"
    return "freeze"


async def _write_audit(
    db: AsyncSession,
    *,
    action_type: AuditAction,
    actor_user_id: uuid.UUID,
    resource_id: uuid.UUID,
    after_state: dict | None = None,
) -> None:
    """Insert an AuditLogEntry for report events.

    Failures are swallowed so that a failed audit write never rolls back
    the primary report operation.

    Requirement 14.1
    """
    try:
        entry = AuditLogEntry(
            action_type=action_type,
            actor_user_id=actor_user_id,
            resource_type="report",
            resource_id=resource_id,
            before_state=None,
            after_state=after_state,
            source_ip="internal",
        )
        db.add(entry)
        await db.flush()
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception(
            "Failed to write audit log entry action=%s resource_id=%s",
            action_type,
            resource_id,
        )


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


async def generate_report(
    trace_id: uuid.UUID,
    format: str,  # "pdf" or "json"
    generated_by_user,  # User ORM
    db: AsyncSession,
) -> Report:
    """Generate an investigation report from an existing trace job.

    Steps:
      1. Load TraceJob; 404 if not found.
      2. Load Case; 404 if not found.
      3. Load attributions (Attribution → Cluster → VASP) for the trace.
      4. Load TypologyTags for the trace.
      5. Load wallet addresses linked to the case.
      6. Extract fund-flow timeline from the stored TraceGraph (if present).
      7. Build a ReportModel from all gathered data.
      8. Compute recommended_action based on risk_score.
      9. Render to bytes using the appropriate renderer.
      10. Compute content_hash = sha256(rendered_bytes).hexdigest().
      11. Persist a Report ORM row and write an audit entry.
      12. db.flush(); return Report.

    Requirements: 11.1, 11.2, 11.3, 11.5, 11.6
    """
    # ------------------------------------------------------------------
    # 1. Load TraceJob
    # ------------------------------------------------------------------
    trace_result = await db.execute(
        select(TraceJob).where(TraceJob.id == trace_id)
    )
    trace_job: TraceJob | None = trace_result.scalars().first()
    if trace_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace job {trace_id} not found",
        )

    # ------------------------------------------------------------------
    # 2. Load Case
    # ------------------------------------------------------------------
    case_result = await db.execute(
        select(Case).where(Case.id == trace_job.case_id, Case.deleted_at.is_(None))
    )
    case: Case | None = case_result.scalars().first()
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case {trace_job.case_id} not found",
        )

    # ------------------------------------------------------------------
    # 3. Load attributions (Attribution → Cluster → VASP)
    # ------------------------------------------------------------------
    attr_result = await db.execute(
        select(Attribution, ClusterModel, VASP)
        .join(ClusterModel, Attribution.cluster_id == ClusterModel.id)
        .join(VASP, Attribution.vasp_id == VASP.id)
        .where(ClusterModel.trace_id == trace_id)
        .order_by(Attribution.confidence_score.desc())
    )
    attribution_rows = attr_result.all()

    attributed_vasps: list[VASPAttribution] = []
    low_confidence_attributions: list[LowConfidenceAttribution] = []

    for attribution, cluster, vasp in attribution_rows:
        vasp_category_str = (
            vasp.category.value
            if hasattr(vasp.category, "value")
            else str(vasp.category)
        )
        conf_score = float(attribution.confidence_score)
        is_low = bool(attribution.low_confidence)
        attributed_vasps.append(
            VASPAttribution(
                vasp_name=vasp.name,
                vasp_category=vasp_category_str,
                confidence_score=conf_score,
                low_confidence=is_low,
            )
        )
        if is_low:
            low_confidence_attributions.append(
                LowConfidenceAttribution(
                    vasp_name=vasp.name,
                    confidence_score=conf_score,
                )
            )

    # ------------------------------------------------------------------
    # 4. Load TypologyTags
    # ------------------------------------------------------------------
    typology_result = await db.execute(
        select(TypologyTag).where(TypologyTag.trace_id == trace_id)
    )
    typology_tags = list(typology_result.scalars().all())

    typologies: list[TypologyFinding] = [
        TypologyFinding(
            typology=tag.typology,
            match_confidence=float(tag.match_confidence),
        )
        for tag in typology_tags
    ]

    # ------------------------------------------------------------------
    # 5. Load wallet addresses linked to the case
    # ------------------------------------------------------------------
    wallet_result = await db.execute(
        select(WalletAddress)
        .join(CaseWallet, WalletAddress.id == CaseWallet.wallet_address_id)
        .where(CaseWallet.case_id == case.id)
    )
    wallet_rows = list(wallet_result.scalars().all())

    wallets: list[WalletSummary] = [
        WalletSummary(address=w.address_plain, chain=w.chain)
        for w in wallet_rows
    ]
    chains_analyzed: list[str] = sorted(
        {w.chain for w in wallet_rows} | {trace_job.chain}
    )

    # ------------------------------------------------------------------
    # 6. Extract fund-flow timeline from TraceGraph (if available)
    # ------------------------------------------------------------------
    fund_flow_timeline: list[TimelineEvent] = []
    total_hops: int = trace_job.current_hop
    total_addresses: int = 0
    total_transactions: int = 0

    graph_result = await db.execute(
        select(TraceGraph).where(TraceGraph.trace_id == trace_id)
    )
    trace_graph: TraceGraph | None = graph_result.scalars().first()

    if trace_graph is not None:
        graph_data = trace_graph.graph_data or {}
        nodes: list[dict] = graph_data.get("nodes", [])
        links: list[dict] = graph_data.get("links", [])

        total_addresses = len(nodes)
        total_transactions = len(links)

        # Build timeline events from edge data; skip edges missing timestamps
        for link in links:
            ts_raw = link.get("timestamp")
            if ts_raw is None:
                continue
            try:
                if isinstance(ts_raw, datetime):
                    ts = ts_raw
                else:
                    ts = datetime.fromisoformat(str(ts_raw))
            except (ValueError, TypeError):
                continue

            fund_flow_timeline.append(
                TimelineEvent(
                    timestamp=ts,
                    from_address=str(link.get("source", "")),
                    to_address=str(link.get("target", "")),
                    amount=float(link.get("amount", 0.0)),
                    chain=str(link.get("chain", trace_job.chain)),
                )
            )

        # Sort chronologically
        fund_flow_timeline.sort(key=lambda e: e.timestamp)

    # ------------------------------------------------------------------
    # 7 & 8. Build ReportModel with risk assessment and recommended action
    # ------------------------------------------------------------------
    risk_score: int = trace_job.risk_score if trace_job.risk_score is not None else 0
    risk_band: str = trace_job.risk_band if trace_job.risk_band is not None else "low"

    report_id = uuid.uuid4()
    generated_at = datetime.now(timezone.utc)

    report_model = ReportModel(
        report_id=report_id,
        generated_at=generated_at,
        generated_by=str(generated_by_user.id),
        case_metadata=CaseMetadata(
            case_id=case.id,
            title=case.title,
            status=case.status.value if hasattr(case.status, "value") else str(case.status),
        ),
        wallets=wallets,
        chains_analyzed=chains_analyzed,
        trace_summary=TraceSummary(
            total_hops=total_hops,
            total_addresses=total_addresses,
            total_transactions=total_transactions,
        ),
        attributed_vasps=attributed_vasps,
        risk_assessment=RiskAssessment(
            score=risk_score,
            band=risk_band,
        ),
        typologies=typologies,
        fund_flow_timeline=fund_flow_timeline,
        recommended_action=_recommended_action(risk_score),  # type: ignore[arg-type]
        low_confidence_attributions=low_confidence_attributions or None,
        content_hash="",
        supervisor_signature=None,
    )

    # ------------------------------------------------------------------
    # 9. Render to bytes and compute content_hash
    # ------------------------------------------------------------------
    s3_key: str | None = None
    json_payload: dict | None = None

    if format == "pdf":
        renderer = WeasyPrintPDFRenderer()
        rendered_bytes = renderer.render(report_model)
        content_hash = hashlib.sha256(rendered_bytes).hexdigest()
        # For PDF we store the S3 key conceptually; in MVP the hash is enough.
        s3_key = f"reports/{report_id}.pdf"
    else:
        # JSON format: use PydanticJSONRenderer (embeds hash internally)
        json_renderer = PydanticJSONRenderer()
        rendered_bytes = json_renderer.render(report_model)
        # Extract the embedded hash from the rendered JSON
        content_hash = hashlib.sha256(
            report_model.model_copy(update={"content_hash": ""}).model_dump_json().encode("utf-8")
        ).hexdigest()
        # Store the parsed JSON payload in the JSONB column
        json_payload = json.loads(rendered_bytes.decode("utf-8"))
        json_payload["content_hash"] = content_hash

    # ------------------------------------------------------------------
    # 11. Persist Report ORM row
    # ------------------------------------------------------------------
    report = Report(
        id=report_id,
        case_id=case.id,
        trace_id=trace_id,
        generated_by=generated_by_user.id,
        format=format,
        s3_key=s3_key,
        json_payload=json_payload,
        content_hash=content_hash,
        supervisor_signature=None,
        status="draft",
    )
    db.add(report)
    await db.flush()

    # ------------------------------------------------------------------
    # 12. Write audit log entry
    # ------------------------------------------------------------------
    await _write_audit(
        db,
        action_type=AuditAction.report_generated,
        actor_user_id=generated_by_user.id,
        resource_id=report.id,
        after_state={
            "report_id": str(report.id),
            "trace_id": str(trace_id),
            "case_id": str(case.id),
            "format": format,
            "status": "draft",
        },
    )

    await db.flush()
    return report


# ---------------------------------------------------------------------------
# sign_report
# ---------------------------------------------------------------------------


async def sign_report(
    report_id: uuid.UUID,
    supervisor,  # User ORM
    db: AsyncSession,
) -> Report:
    """Supervisor approval: sign a report and mark it as supervisor-approved.

    Steps:
      1. Load Report; 404 if not found.
      2. Compute supervisor_signature = "{user_id}:{iso_timestamp}:{content_hash}".
      3. Set status = "supervisor-approved".
      4. Write AuditLogEntry(report_signed).
      5. db.flush(); return Report.

    Requirements: 11.6, 11.7
    """
    # ------------------------------------------------------------------
    # 1. Load Report
    # ------------------------------------------------------------------
    report_result = await db.execute(
        select(Report).where(Report.id == report_id)
    )
    report: Report | None = report_result.scalars().first()
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {report_id} not found",
        )

    # ------------------------------------------------------------------
    # 2. Build supervisor signature
    # ------------------------------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()
    report.supervisor_signature = (
        f"{supervisor.id}:{now_iso}:{report.content_hash}"
    )

    # ------------------------------------------------------------------
    # 3. Update status
    # ------------------------------------------------------------------
    report.status = "supervisor-approved"
    await db.flush()

    # ------------------------------------------------------------------
    # 4. Write audit log entry
    # ------------------------------------------------------------------
    await _write_audit(
        db,
        action_type=AuditAction.report_signed,
        actor_user_id=supervisor.id,
        resource_id=report.id,
        after_state={
            "report_id": str(report.id),
            "status": "supervisor-approved",
            "supervisor_signature": report.supervisor_signature,
        },
    )

    await db.flush()
    return report
