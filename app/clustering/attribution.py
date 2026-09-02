"""Attribution pipeline: clusters → VASP DB lookup → confidence score → ORM records.

Implements the full attribution pipeline described in the design doc:
  1. Run the appropriate clustering heuristic for the given chain.
  2. Persist each Cluster to the database.
  3. Query VASPAddress for any address in the cluster on the same chain.
  4. Compute a confidence score and emit Attribution ORM records.
  5. Emit TypologyTag records for mixer / bridge VASPs.

Requirements: 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clustering.heuristics import (
    Cluster,
    cluster_bitcoin_cio,
    cluster_deposit_pattern,
)
from app.clustering.models import Attribution
from app.clustering.models import Cluster as ClusterModel
from app.typology.models import TypologyTag
from app.vasp_db.models import VASP, VASPAddress


# ---------------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------------


def compute_confidence_score(
    address_match_ratio: float,
    volume_similarity: float,
    behavioral_similarity: float,
    temporal_proximity: float,
) -> float:
    """Return a weighted attribution confidence score in [0.0, 100.0].

    Formula: (0.4*r + 0.3*v + 0.2*b + 0.1*t) * 100

    All inputs are clamped to [0.0, 1.0] before the calculation so
    out-of-range values never produce a result outside [0.0, 100.0].

    Args:
        address_match_ratio:   Fraction of cluster addresses found in the VASP DB.
        volume_similarity:     Cosine similarity of volume profile (0–1).
        behavioral_similarity: Pattern-match score (0–1).
        temporal_proximity:    Recency weight (0–1).

    Returns:
        Rounded float in [0.0, 100.0].

    Requirements: 6.5, 6.6
    """
    clamped = [
        max(0.0, min(1.0, x))
        for x in [
            address_match_ratio,
            volume_similarity,
            behavioral_similarity,
            temporal_proximity,
        ]
    ]
    raw = (
        0.4 * clamped[0]
        + 0.3 * clamped[1]
        + 0.2 * clamped[2]
        + 0.1 * clamped[3]
    ) * 100
    return round(raw, 2)


# ---------------------------------------------------------------------------
# VASP category → typology label mapping
# ---------------------------------------------------------------------------

_VASP_TYPOLOGY: dict[str, str] = {
    "mixer": "obfuscation service",
    "bridge": "cross-chain bridge",
}


# ---------------------------------------------------------------------------
# Attribution pipeline
# ---------------------------------------------------------------------------


async def run_attribution_pipeline(
    trace_id: uuid.UUID,
    chain: str,
    G: nx.DiGraph,
    db: AsyncSession,
) -> list[Attribution]:
    """Run the full attribution pipeline for one trace job.

    Steps:
      1. Select the correct clustering heuristic based on *chain*.
      2. For each resulting Cluster:
         a. Persist a ``ClusterModel`` row to the database.
         b. Query ``VASPAddress`` for any cluster address on the same chain.
         c. If at least one address matches a known VASP:
            - Compute ``confidence_score`` using the weighted formula.
            - Create and stage an ``Attribution`` record.
            - If the VASP category is ``mixer`` or ``bridge``, also stage a
              ``TypologyTag`` for each matched address.
      3. Flush all staged objects so they receive database-assigned defaults
         (e.g. ``created_at``) without committing the outer transaction.
      4. Return the list of ``Attribution`` ORM objects.

    Args:
        trace_id: UUID of the parent ``TraceJob``.
        chain:    Blockchain identifier (BTC | ETH | TRX | BSC | SOL | MATIC).
        G:        Directed transaction graph built by the trace worker.
        db:       Active async SQLAlchemy session (managed by the caller).

    Returns:
        List of ``Attribution`` ORM objects added during this pipeline run.
        Returns an empty list if no clusters could be attributed to a known VASP.

    Requirements: 6.3, 6.4, 6.7, 6.8, 6.9
    """
    # ------------------------------------------------------------------
    # Step 1 — cluster
    # ------------------------------------------------------------------
    if chain == "BTC":
        clusters: list[Cluster] = cluster_bitcoin_cio(G)
    else:
        clusters = cluster_deposit_pattern(G, chain)

    attributions: list[Attribution] = []

    for cluster in clusters:
        # ------------------------------------------------------------------
        # Step 2a — persist cluster
        # ------------------------------------------------------------------
        cluster_orm = ClusterModel(
            trace_id=trace_id,
            chain=cluster.chain,
            addresses=sorted(cluster.addresses),  # stable JSON array
            cluster_method=cluster.method,
        )
        db.add(cluster_orm)
        # Flush to obtain the auto-generated primary key before referencing it
        await db.flush()

        # ------------------------------------------------------------------
        # Step 2b — look up any cluster address in VASPAddress
        # ------------------------------------------------------------------
        address_list = list(cluster.addresses)

        vasp_addr_result = await db.execute(
            select(VASPAddress)
            .where(
                VASPAddress.chain == chain,
                VASPAddress.address.in_(address_list),
            )
        )
        matched_vasp_addresses: list[VASPAddress] = list(
            vasp_addr_result.scalars().all()
        )

        if not matched_vasp_addresses:
            # No VASP match for this cluster — skip attribution
            continue

        # Group matched addresses by VASP id so we emit one Attribution per VASP
        vasp_to_matched: dict[uuid.UUID, list[VASPAddress]] = {}
        for va in matched_vasp_addresses:
            vasp_to_matched.setdefault(va.vasp_id, []).append(va)

        for vasp_id, vasp_addrs in vasp_to_matched.items():
            # Fetch the parent VASP record (needed for category check)
            vasp_result = await db.execute(
                select(VASP).where(VASP.id == vasp_id)
            )
            vasp: VASP | None = vasp_result.scalars().first()
            if vasp is None:
                continue  # referential integrity violation — skip gracefully

            # ------------------------------------------------------------------
            # Step 2c — compute confidence score
            # ------------------------------------------------------------------
            matched_count = len(vasp_addrs)
            cluster_size = len(cluster.addresses)
            address_match_ratio = matched_count / cluster_size if cluster_size > 0 else 0.0

            # Free-tier defaults for metrics we cannot compute without volume history
            volume_similarity = 0.5
            behavioral_similarity = 0.5
            temporal_proximity = 0.5

            score = compute_confidence_score(
                address_match_ratio=address_match_ratio,
                volume_similarity=volume_similarity,
                behavioral_similarity=behavioral_similarity,
                temporal_proximity=temporal_proximity,
            )

            attribution = Attribution(
                cluster_id=cluster_orm.id,
                vasp_id=vasp_id,
                confidence_score=Decimal(str(score)),
                low_confidence=(score < 40),
                address_match_ratio=Decimal(str(round(address_match_ratio, 4))),
                volume_similarity=Decimal("0.5000"),
                behavioral_similarity=Decimal("0.5000"),
                temporal_proximity=Decimal("0.5000"),
            )
            db.add(attribution)
            attributions.append(attribution)

            # ------------------------------------------------------------------
            # Typology tags for mixer / bridge VASPs
            # ------------------------------------------------------------------
            vasp_category_str = (
                vasp.category.value
                if hasattr(vasp.category, "value")
                else str(vasp.category)
            )
            typology_label = _VASP_TYPOLOGY.get(vasp_category_str)

            if typology_label:
                for va in vasp_addrs:
                    tag = TypologyTag(
                        trace_id=trace_id,
                        address=va.address,
                        typology=typology_label,
                        match_confidence=Decimal("0.9000"),
                    )
                    db.add(tag)

    # ------------------------------------------------------------------
    # Step 3 — flush all staged objects
    # ------------------------------------------------------------------
    await db.flush()

    return attributions
