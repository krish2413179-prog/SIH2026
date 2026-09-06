"""Production inference service for wallet suspicion detection with explainability.

Loads the trained ensemble model, extracts features from wallet transactions or graphs,
computes suspicion scores (0-100), risk bands, confidence, and human-readable explanations.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np

from app.ml.features import FEATURE_NAMES, WalletFeatureExtractor

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "wallet_suspicion_model.joblib"
METADATA_PATH = ARTIFACTS_DIR / "model_metadata.json"


class WalletSuspicionDetector:
    """Production inference service for predicting wallet suspicion."""

    def __init__(self, model_path: Path | str | None = None) -> None:
        self.model_path = Path(model_path) if model_path else MODEL_PATH
        self.extractor = WalletFeatureExtractor()
        self.bundle: dict[str, Any] | None = None
        self.metadata: dict[str, Any] = {}
        self._load_model()

    def _load_model(self) -> None:
        """Load trained model bundle and metadata from disk if present."""
        if self.model_path.exists():
            try:
                self.bundle = joblib.load(self.model_path)
                logger.info(f"Loaded trained wallet suspicion model from {self.model_path}")
            except Exception as e:
                logger.error(f"Failed to load model from {self.model_path}: {e}")
                self.bundle = None

        if METADATA_PATH.exists():
            try:
                with open(METADATA_PATH, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load metadata from {METADATA_PATH}: {e}")

    @property
    def is_trained(self) -> bool:
        """Return True if model is loaded and ready for inference."""
        return self.bundle is not None and "model" in self.bundle and "scaler" in self.bundle

    def get_model_info(self) -> dict[str, Any]:
        """Return metadata and performance metrics of the currently loaded model."""
        return {
            "is_trained": self.is_trained,
            "version": self.bundle.get("version", "unknown") if self.bundle else None,
            "trained_at": self.metadata.get("trained_at"),
            "accuracy": self.metadata.get("accuracy"),
            "roc_auc": self.metadata.get("roc_auc"),
            "f1_score": self.metadata.get("f1_score"),
            "precision": self.metadata.get("precision"),
            "recall": self.metadata.get("recall"),
            "sample_count": self.metadata.get("sample_count"),
            "top_features": self.metadata.get("top_features", []),
        }

    def _generate_explanations(
        self,
        features: dict[str, float],
        prob: float,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Identify key contributing features and detected behavioral patterns."""
        contributing_factors: list[dict[str, Any]] = []
        detected_patterns: list[str] = []

        # Rapid forwarding
        rf = features.get("rapid_forwarding_ratio", 0.0)
        if rf >= 0.5:
            contributing_factors.append({
                "feature": "rapid_forwarding_ratio",
                "name": "Rapid Forwarding Velocity",
                "value": f"{rf * 100:.1f}%",
                "severity": "high" if rf >= 0.75 else "medium",
                "description": f"{rf * 100:.1f}% of funds forwarded within 60 minutes of arrival.",
            })
            detected_patterns.append("Rapid Pass-Through / Peeling Transit")

        # Zero balance retention
        ret = features.get("net_balance_retention", 0.0)
        out_cnt = features.get("out_tx_count", 0.0)
        if ret <= 0.05 and out_cnt >= 2:
            contributing_factors.append({
                "feature": "net_balance_retention",
                "name": "Zero Balance Retention",
                "value": f"{ret * 100:.1f}%",
                "severity": "medium",
                "description": "Wallet retains near 0% of received funds; acts as transit intermediary.",
            })
            detected_patterns.append("Transit / Mule Intermediary")

        # Round amount structuring
        rar = features.get("round_amount_ratio", 0.0)
        if rar >= 0.4 and features.get("total_tx_count", 0) >= 4:
            contributing_factors.append({
                "feature": "round_amount_ratio",
                "name": "Structuring Indicator (Round Amounts)",
                "value": f"{rar * 100:.1f}%",
                "severity": "high" if rar >= 0.7 else "medium",
                "description": "Unusually high frequency of rounded transaction amounts.",
            })
            detected_patterns.append("Structuring / Smurfing Pattern")

        # Fan-out dispersion
        fan_out = features.get("fan_out_ratio", 0.0)
        if fan_out >= 3.0:
            contributing_factors.append({
                "feature": "fan_out_ratio",
                "name": "High Fan-Out Dispersion",
                "value": f"{fan_out:.1f}x",
                "severity": "medium",
                "description": f"Outputs spread across {int(features.get('out_degree', 0))} unique destination addresses.",
            })
            detected_patterns.append("Layering Dispersion")

        # Fan-in aggregation
        fan_in = features.get("fan_in_ratio", 0.0)
        if fan_in >= 4.0:
            contributing_factors.append({
                "feature": "fan_in_ratio",
                "name": "High Fan-In Consolidation",
                "value": f"{fan_in:.1f}x",
                "severity": "medium",
                "description": f"Funds aggregated from {int(features.get('in_degree', 0))} disparate sources.",
            })
            detected_patterns.append("Collection / Inflow Aggregation")

        # Burst volume ratio
        bvr = features.get("burst_volume_ratio", 0.0)
        if bvr >= 0.75 and features.get("total_tx_count", 0) >= 3:
            contributing_factors.append({
                "feature": "burst_volume_ratio",
                "name": "Sudden Volume Burst",
                "value": f"{bvr * 100:.1f}%",
                "severity": "high",
                "description": f"{bvr * 100:.1f}% of all historical volume occurred in a single 1-hour window.",
            })
            detected_patterns.append("Volume Anomaly Burst")

        # High risk exposure
        hre = features.get("high_risk_entity_exposure", 0.0)
        if hre > 0:
            contributing_factors.append({
                "feature": "high_risk_entity_exposure",
                "name": "High-Risk Entity Interaction",
                "value": f"{hre * 100:.1f}%",
                "severity": "high",
                "description": "Direct interaction with flagged mixer, bridge, or darknet entity.",
            })
            detected_patterns.append("Direct High-Risk Exposure")

        # Night activity
        nar = features.get("night_activity_ratio", 0.0)
        if nar >= 0.6 and features.get("total_tx_count", 0) >= 5:
            contributing_factors.append({
                "feature": "night_activity_ratio",
                "name": "Non-Standard Hours Activity",
                "value": f"{nar * 100:.1f}%",
                "severity": "low",
                "description": "Over 60% of transactions executed between 00:00 and 06:00 UTC.",
            })

        if not detected_patterns and prob >= 0.5:
            detected_patterns.append("Complex Multivariate Anomaly")

        return contributing_factors, detected_patterns

    def predict_wallet(
        self,
        wallet_address: str,
        transactions: Sequence[Any],
        chain: str = "ETH",
    ) -> dict[str, Any]:
        """Predict whether a wallet address is suspicious given its group of transactions."""
        # 1. Extract feature dictionary
        features = self.extractor.extract_from_transactions(wallet_address, transactions)

        # 2. If model is available, run inference; else fallback to rule-based heuristic
        if self.is_trained and self.bundle is not None:
            model = self.bundle["model"]
            scaler = self.bundle["scaler"]

            feature_vector = np.array(
                [[float(features.get(name, 0.0)) for name in FEATURE_NAMES]],
                dtype=np.float32,
            )
            scaled_vector = scaler.transform(feature_vector)
            prob = float(model.predict_proba(scaled_vector)[0, 1])
        else:
            # Fallback heuristic calculation if model not yet trained
            rf = features.get("rapid_forwarding_ratio", 0.0)
            hre = features.get("high_risk_entity_exposure", 0.0)
            bvr = features.get("burst_volume_ratio", 0.0)
            prob = min(1.0, 0.4 * rf + 0.4 * hre + 0.2 * bvr)

        score = max(0, min(100, round(prob * 100)))
        is_suspicious = bool(prob >= 0.5)

        if score >= 70:
            band = "high"
        elif score >= 40:
            band = "medium"
        else:
            band = "low"

        confidence = round(float(abs(prob - 0.5) * 2.0), 4)

        factors, patterns = self._generate_explanations(features, prob)

        return {
            "wallet_address": wallet_address,
            "chain": chain,
            "is_suspicious": is_suspicious,
            "suspicion_score": score,
            "suspicion_probability": round(prob, 4),
            "risk_band": band,
            "confidence": confidence,
            "detected_patterns": patterns,
            "contributing_factors": factors,
            "extracted_features": features,
            "model_version": self.bundle.get("version", "1.0.0") if self.bundle else "heuristic_fallback",
        }

    def predict_batch(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Run batch prediction on a list of wallet transaction records."""
        results = []
        for item in items:
            addr = item.get("wallet_address", "")
            txs = item.get("transactions", [])
            chain = item.get("chain", "ETH")
            res = self.predict_wallet(addr, txs, chain=chain)
            results.append(res)
        return results


# Thread-safe singleton
_detector_instance: WalletSuspicionDetector | None = None
_lock = threading.Lock()


def get_detector() -> WalletSuspicionDetector:
    """Return singleton instance of WalletSuspicionDetector."""
    global _detector_instance
    with _lock:
        if _detector_instance is None:
            _detector_instance = WalletSuspicionDetector()
        return _detector_instance


def reload_detector() -> WalletSuspicionDetector:
    """Reload model artifact after fresh training."""
    global _detector_instance
    with _lock:
        _detector_instance = WalletSuspicionDetector()
        return _detector_instance
