"""Machine Learning Module for Blockchain Wallet Suspicion Detection.

Exposes:
- WalletFeatureExtractor: Extracts 22+ topological, statistical, and behavioral features.
- WalletSuspicionTrainer: Trains and evaluates ensemble classifiers on transaction groups.
- WalletSuspicionDetector: Production inference service with explainability.
"""

from app.ml.features import WalletFeatureExtractor, FEATURE_NAMES
from app.ml.detector import WalletSuspicionDetector, get_detector

__all__ = [
    "WalletFeatureExtractor",
    "FEATURE_NAMES",
    "WalletSuspicionDetector",
    "get_detector",
]
