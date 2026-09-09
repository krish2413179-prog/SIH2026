"""Feature extraction engine for cryptocurrency wallet transaction groups.

Extracts 25 domain-specific topological, statistical, and behavioral features
from raw transactions or a NetworkX transaction graph.

Designed for anti-money laundering (AML), peeling chain detection,
structuring recognition, and anomaly detection.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

import networkx as nx
import numpy as np

# Canonical feature list in strict deterministic order
FEATURE_NAMES: list[str] = [
    "total_tx_count",
    "in_tx_count",
    "out_tx_count",
    "in_out_tx_ratio",
    "total_inflow",
    "total_outflow",
    "net_balance_retention",
    "mean_tx_amount",
    "std_tx_amount",
    "max_tx_amount",
    "amount_gini",
    "round_amount_ratio",
    "dust_tx_ratio",
    "lifespan_hours",
    "tx_per_day",
    "burst_volume_ratio",
    "rapid_forwarding_ratio",
    "in_degree",
    "out_degree",
    "counterparty_dispersion",
    "fan_in_ratio",
    "fan_out_ratio",
    "reciprocity_ratio",
    "night_activity_ratio",
    "high_risk_entity_exposure",
]


def _to_float(val: Any) -> float:
    """Safely convert any numeric representation to float."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return 0.0


def _parse_timestamp(val: Any) -> datetime | None:
    """Parse datetime from datetime object, timestamp float, or ISO string."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(float(val), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(val, str):
        try:
            # Handle ISO format
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return None


def _calc_gini(values: list[float]) -> float:
    """Calculate Gini coefficient of a list of positive numbers."""
    if not values or len(values) < 2:
        return 0.0
    arr = np.array(values, dtype=np.float64)
    if np.all(arr <= 0):
        return 0.0
    arr = np.sort(arr)
    n = len(arr)
    index = np.arange(1, n + 1)
    return float((np.sum((2 * index - n - 1) * arr)) / (n * np.sum(arr)))


class WalletFeatureExtractor:
    """Extracts machine learning features for a given wallet address from its transactions."""

    def __init__(self, dust_threshold: float = 0.001, rapid_forward_window_sec: float = 3600.0) -> None:
        self.dust_threshold = dust_threshold
        self.rapid_forward_window_sec = rapid_forward_window_sec

    def extract_from_transactions(
        self,
        wallet_address: str,
        transactions: Sequence[Any],
    ) -> dict[str, float]:
        """Extract a dictionary of features from a sequence of transactions for a target wallet.

        Transactions can be dicts, RawTransaction dataclass instances, or attribute objects.
        """
        w_lower = wallet_address.strip().lower()

        in_txs: list[dict[str, Any]] = []
        out_txs: list[dict[str, Any]] = []
        all_amounts: list[float] = []
        in_senders: set[str] = set()
        out_receivers: set[str] = set()
        timestamps: list[datetime] = []
        high_risk_flags = 0

        for tx in transactions:
            # Normalise attributes
            if isinstance(tx, dict):
                from_addr = str(tx.get("from_addr") or tx.get("from") or "").strip().lower()
                to_addr = str(tx.get("to_addr") or tx.get("to") or "").strip().lower()
                amount = _to_float(tx.get("amount", 0.0))
                ts = _parse_timestamp(tx.get("timestamp") or tx.get("time"))
                is_risk = bool(tx.get("is_risk") or tx.get("is_mixer") or tx.get("is_bridge"))
            else:
                from_addr = str(getattr(tx, "from_addr", "") or getattr(tx, "from", "")).strip().lower()
                to_addr = str(getattr(tx, "to_addr", "") or getattr(tx, "to", "")).strip().lower()
                amount = _to_float(getattr(tx, "amount", 0.0))
                ts = _parse_timestamp(getattr(tx, "timestamp", None))
                is_risk = bool(getattr(tx, "is_bridge", False))

            if is_risk:
                high_risk_flags += 1

            if ts:
                timestamps.append(ts)

            all_amounts.append(amount)

            is_in = (to_addr == w_lower)
            is_out = (from_addr == w_lower)

            if is_in:
                in_txs.append({"amount": amount, "timestamp": ts, "from": from_addr})
                if from_addr and from_addr != w_lower:
                    in_senders.add(from_addr)
            if is_out:
                out_txs.append({"amount": amount, "timestamp": ts, "to": to_addr})
                if to_addr and to_addr != w_lower:
                    out_receivers.add(to_addr)

        total_tx = len(transactions)
        in_count = len(in_txs)
        out_count = len(out_txs)

        # Basic counts & ratios
        in_out_ratio = float(in_count) / float(out_count + 1)
        total_inflow = sum(t["amount"] for t in in_txs)
        total_outflow = sum(t["amount"] for t in out_txs)
        net_retention = (total_inflow - total_outflow) / (total_inflow + 1e-6) if total_inflow > 0 else 0.0
        # Clamp retention to [-1.0, 1.0]
        net_retention = max(-1.0, min(1.0, net_retention))

        # Amount statistics
        mean_amount = float(np.mean(all_amounts)) if all_amounts else 0.0
        std_amount = float(np.std(all_amounts)) if all_amounts else 0.0
        max_amount = max(all_amounts) if all_amounts else 0.0
        amount_gini = _calc_gini(all_amounts)

        # Structuring indicators
        round_count = 0
        dust_count = 0
        for amt in all_amounts:
            if amt > 0:
                # Check for round numbers (e.g. 10.0, 50.0, 100.0, 0.5, 1000.0)
                if abs(amt - round(amt)) < 1e-4 or abs(amt * 10 - round(amt * 10)) < 1e-4:
                    round_count += 1
                if amt < self.dust_threshold:
                    dust_count += 1

        round_amount_ratio = float(round_count) / float(total_tx) if total_tx > 0 else 0.0
        dust_tx_ratio = float(dust_count) / float(total_tx) if total_tx > 0 else 0.0

        # Temporal metrics
        timestamps_sorted = sorted([t for t in timestamps if t is not None])
        if len(timestamps_sorted) >= 2:
            duration_sec = (timestamps_sorted[-1] - timestamps_sorted[0]).total_seconds()
            lifespan_hours = max(0.01, duration_sec / 3600.0)
            duration_days = max(1.0, duration_sec / 86400.0)
            tx_per_day = float(total_tx) / duration_days
        else:
            lifespan_hours = 0.0
            tx_per_day = float(total_tx)

        # Burst volume ratio (highest volume in any 1-hour rolling window / total volume)
        burst_volume_ratio = 0.0
        total_vol = total_inflow + total_outflow
        if total_vol > 0 and len(timestamps_sorted) > 0:
            # Pair each transaction with its timestamp and amount
            timed_amounts: list[tuple[datetime, float]] = []
            for tx_item in in_txs + out_txs:
                if tx_item.get("timestamp"):
                    timed_amounts.append((tx_item["timestamp"], tx_item["amount"]))
            timed_amounts.sort(key=lambda x: x[0])

            max_hour_vol = 0.0
            left = 0
            curr_win_vol = 0.0
            for right in range(len(timed_amounts)):
                curr_win_vol += timed_amounts[right][1]
                while (timed_amounts[right][0] - timed_amounts[left][0]).total_seconds() > 3600.0:
                    curr_win_vol -= timed_amounts[left][1]
                    left += 1
                if curr_win_vol > max_hour_vol:
                    max_hour_vol = curr_win_vol
            burst_volume_ratio = min(1.0, max_hour_vol / total_vol)

        # Rapid forwarding ratio (funds arriving and leaving within rapid_forward_window_sec)
        rapid_forward_count = 0
        if in_txs and out_txs:
            for ot in out_txs:
                o_ts = ot.get("timestamp")
                if not o_ts:
                    continue
                # Look for an in_tx that preceded this out_tx within rapid_forward_window_sec
                for it in in_txs:
                    i_ts = it.get("timestamp")
                    if i_ts and 0 <= (o_ts - i_ts).total_seconds() <= self.rapid_forward_window_sec:
                        rapid_forward_count += 1
                        break
            rapid_forwarding_ratio = float(rapid_forward_count) / float(out_count)
        else:
            rapid_forwarding_ratio = 0.0

        # Topological graph metrics
        in_degree = len(in_senders)
        out_degree = len(out_receivers)
        counterparty_dispersion = float(in_degree + out_degree) / float(total_tx + 1)
        fan_in_ratio = float(in_degree) / float(out_degree + 1)
        fan_out_ratio = float(out_degree) / float(in_degree + 1)

        # Reciprocity (interacted as both sender and receiver)
        common_peers = in_senders.intersection(out_receivers)
        all_unique_peers = in_senders.union(out_receivers)
        reciprocity_ratio = float(len(common_peers)) / float(len(all_unique_peers)) if all_unique_peers else 0.0

        # Night activity (00:00 - 06:00 UTC)
        night_txs = sum(1 for ts in timestamps_sorted if 0 <= ts.hour < 6)
        night_activity_ratio = float(night_txs) / float(total_tx) if total_tx > 0 else 0.0

        # High risk entity exposure
        high_risk_exposure = float(high_risk_flags) / float(total_tx + 1)

        feature_dict: dict[str, float] = {
            "total_tx_count": float(total_tx),
            "in_tx_count": float(in_count),
            "out_tx_count": float(out_count),
            "in_out_tx_ratio": round(in_out_ratio, 4),
            "total_inflow": round(total_inflow, 6),
            "total_outflow": round(total_outflow, 6),
            "net_balance_retention": round(net_retention, 4),
            "mean_tx_amount": round(mean_amount, 6),
            "std_tx_amount": round(std_amount, 6),
            "max_tx_amount": round(max_amount, 6),
            "amount_gini": round(amount_gini, 4),
            "round_amount_ratio": round(round_amount_ratio, 4),
            "dust_tx_ratio": round(dust_tx_ratio, 4),
            "lifespan_hours": round(lifespan_hours, 2),
            "tx_per_day": round(tx_per_day, 2),
            "burst_volume_ratio": round(burst_volume_ratio, 4),
            "rapid_forwarding_ratio": round(rapid_forwarding_ratio, 4),
            "in_degree": float(in_degree),
            "out_degree": float(out_degree),
            "counterparty_dispersion": round(counterparty_dispersion, 4),
            "fan_in_ratio": round(fan_in_ratio, 4),
            "fan_out_ratio": round(fan_out_ratio, 4),
            "reciprocity_ratio": round(reciprocity_ratio, 4),
            "night_activity_ratio": round(night_activity_ratio, 4),
            "high_risk_entity_exposure": round(high_risk_exposure, 4),
        }
        return feature_dict

    def extract_from_graph(self, G: nx.DiGraph, wallet_address: str) -> dict[str, float]:
        """Extract features directly from a NetworkX transaction graph.

        This is the preferred method for real-wallet ML scoring because it can
        read entity_type labels from neighbor nodes (set by the VASP finder,
        intel lookup, and deposit sweep detector) and propagate them as
        is_risk/is_mixer flags, giving the ML model the full graph context.
        """
        w_lower = wallet_address.strip().lower()
        node = None
        for n in G.nodes():
            if str(n).strip().lower() == w_lower:
                node = n
                break

        if node is None or node not in G:
            return {name: 0.0 for name in FEATURE_NAMES}

        HIGH_RISK_TYPES = frozenset({
            "mixer", "tumbler", "darknet", "sanctioned",
            "ransomware", "bridge", "scam",
        })

        tx_list: list[dict[str, Any]] = []

        # Outgoing edges — enrich is_risk from the target node's entity_type
        for _, to_node, data in G.out_edges(node, data=True):
            to_attrs = G.nodes[to_node]
            neighbor_entity = str(to_attrs.get("entity_type", "")).lower()
            is_high_risk_neighbor = neighbor_entity in HIGH_RISK_TYPES
            tx_list.append({
                "from_addr": node,
                "to_addr": to_node,
                "amount": data.get("amount", 0.0),
                "timestamp": data.get("timestamp"),
                # Mark as risk if edge flagged OR destination is a known high-risk entity
                "is_risk": bool(data.get("is_risk")) or is_high_risk_neighbor,
                "is_mixer": bool(data.get("is_mixer")) or neighbor_entity in ("mixer", "tumbler"),
                "is_bridge": bool(data.get("is_bridge")),
            })

        # Incoming edges — enrich is_risk from the source node's entity_type
        for from_node, _, data in G.in_edges(node, data=True):
            from_attrs = G.nodes[from_node]
            sender_entity = str(from_attrs.get("entity_type", "")).lower()
            is_high_risk_sender = sender_entity in HIGH_RISK_TYPES
            tx_list.append({
                "from_addr": from_node,
                "to_addr": node,
                "amount": data.get("amount", 0.0),
                "timestamp": data.get("timestamp"),
                "is_risk": bool(data.get("is_risk")) or is_high_risk_sender,
                "is_mixer": bool(data.get("is_mixer")) or sender_entity in ("mixer", "tumbler"),
                "is_bridge": bool(data.get("is_bridge")),
            })

        return self.extract_from_transactions(wallet_address, tx_list)

    def extract_vector(self, wallet_address: str, transactions: Sequence[Any]) -> list[float]:
        """Return feature values as an ordered list of floats matching FEATURE_NAMES."""
        fdict = self.extract_from_transactions(wallet_address, transactions)
        return [float(fdict.get(name, 0.0)) for name in FEATURE_NAMES]
