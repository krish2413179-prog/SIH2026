"""TypologyClassifier — runs all detectors concurrently.

Orchestrates the seven TypologyDetector implementations over a transaction
graph for a given address, persists qualifying results as TypologyTag rows,
and returns the created tags.

Covers Requirements: 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from app.typology.detectors import (
    BridgeAbuseDetector,
    DarknetDetector,
    FraudAggregationDetector,
    LayeringDetector,
    MixerTumblerDetector,
    PeelChainDetector,
    RansomwareDetector,
)
from app.typology.models import TypologyTag

CONFIDENCE_THRESHOLD = 0.60


class TypologyClassifier:
    """Run all typology detectors concurrently and persist qualifying results.

    Each detector runs in a thread-pool executor so CPU-bound graph analysis
    doesn't block the event loop. Only detections with
    ``match_confidence >= CONFIDENCE_THRESHOLD`` (0.60) are saved.
    """

    def __init__(self) -> None:
        self.detectors = [
            LayeringDetector(),
            PeelChainDetector(),
            MixerTumblerDetector(),
            BridgeAbuseDetector(),
            DarknetDetector(),
            RansomwareDetector(),
            FraudAggregationDetector(),
        ]

    async def classify(
        self,
        trace_id: uuid.UUID,
        address: str,
        G: nx.DiGraph,
        db: AsyncSession,
    ) -> list[TypologyTag]:
        """Run all detectors concurrently via asyncio.gather + run_in_executor.

        For each DetectionResult with match_confidence >= CONFIDENCE_THRESHOLD:
        - Serialise sub_graph to node_link_data JSON if present
        - Create and flush a TypologyTag ORM row

        Args:
            trace_id: UUID of the parent trace job.
            address:  Blockchain address being analysed.
            G:        Transaction directed graph.
            db:       Active async SQLAlchemy session.

        Returns:
            List of persisted TypologyTag objects (may be empty).
        """
        loop = asyncio.get_event_loop()

        async def run_detector(detector):
            try:
                result = await loop.run_in_executor(None, detector.detect, G, address)
                return result
            except Exception:
                return None

        results = await asyncio.gather(*[run_detector(d) for d in self.detectors])

        tags: list[TypologyTag] = []
        for result in results:
            if result is None:
                continue
            if result.match_confidence < CONFIDENCE_THRESHOLD:
                continue

            sub_graph_data = None
            if result.sub_graph is not None:
                from networkx.readwrite import json_graph  # local import — optional dep

                sub_graph_data = json_graph.node_link_data(result.sub_graph)

            tag = TypologyTag(
                trace_id=trace_id,
                address=address,
                typology=result.typology,
                match_confidence=Decimal(str(round(result.match_confidence, 4))),
                sub_graph=sub_graph_data,
            )
            db.add(tag)
            tags.append(tag)

        if tags:
            await db.flush()

        return tags
