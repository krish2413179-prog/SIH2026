"""Model training pipeline for cryptocurrency wallet suspicion classification.

Trains an ensemble of RobustScaler + RandomForestClassifier + HistGradientBoostingClassifier.
Computes ROC-AUC, Precision, Recall, F1, 5-fold CV score, and feature importances.
Saves serialized model artifacts and metadata.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, VotingClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.preprocessing import RobustScaler

from app.ml.features import FEATURE_NAMES

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "wallet_suspicion_model.joblib"
METADATA_PATH = ARTIFACTS_DIR / "model_metadata.json"


class WalletSuspicionTrainer:
    """Trains, evaluates, and serializes the wallet suspicion ML ensemble model."""

    def __init__(self, random_state: int = 42) -> None:
        self.random_state = random_state
        self.scaler = RobustScaler()
        self.rf = RandomForestClassifier(
            n_estimators=150,
            max_depth=14,
            min_samples_split=4,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=self.random_state,
            n_jobs=-1,
        )
        self.hgb = HistGradientBoostingClassifier(
            max_iter=150,
            max_depth=8,
            learning_rate=0.08,
            l2_regularization=0.1,
            class_weight="balanced",
            random_state=self.random_state,
        )
        self.ensemble = VotingClassifier(
            estimators=[
                ("rf", self.rf),
                ("hgb", self.hgb),
            ],
            voting="soft",
        )
        self.metrics: dict[str, Any] = {}
        self.feature_importances: dict[str, float] = {}

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        test_size: float = 0.2,
        cv_folds: int = 5,
    ) -> dict[str, Any]:
        """Train the ensemble model, perform cross-validation, and evaluate on hold-out test set."""
        logger.info(f"Starting training on {len(X)} samples with {X.shape[1]} features...")

        # Stratified train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, stratify=y, random_state=self.random_state
        )

        # Scale features using RobustScaler (handles crypto volume outliers)
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        # 5-fold Cross Validation on training set
        cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=self.random_state)
        cv_scores = cross_val_score(self.ensemble, X_train_scaled, y_train, cv=cv, scoring="roc_auc", n_jobs=-1)
        mean_cv_roc_auc = float(np.mean(cv_scores))
        std_cv_roc_auc = float(np.std(cv_scores))

        # Train final ensemble on full training set
        self.ensemble.fit(X_train_scaled, y_train)

        # Evaluate on holdout test set
        y_pred = self.ensemble.predict(X_test_scaled)
        y_prob = self.ensemble.predict_proba(X_test_scaled)[:, 1]

        acc = float(accuracy_score(y_test, y_pred))
        prec = float(precision_score(y_test, y_pred, zero_division=0))
        rec = float(recall_score(y_test, y_pred, zero_division=0))
        f1 = float(f1_score(y_test, y_pred, zero_division=0))
        roc_auc = float(roc_auc_score(y_test, y_prob))
        cm = confusion_matrix(y_test, y_pred).tolist()

        # Extract feature importances from the fitted RandomForest component
        rf_fitted = self.ensemble.named_estimators_["rf"]
        raw_importances = rf_fitted.feature_importances_
        sorted_indices = np.argsort(raw_importances)[::-1]

        self.feature_importances = {
            FEATURE_NAMES[idx]: round(float(raw_importances[idx]), 4)
            for idx in sorted_indices
        }

        self.metrics = {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "sample_count": int(len(X)),
            "train_samples": int(len(X_train)),
            "test_samples": int(len(X_test)),
            "features_count": int(X.shape[1]),
            "accuracy": round(acc, 4),
            "roc_auc": round(roc_auc, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1_score": round(f1, 4),
            "cv_mean_roc_auc": round(mean_cv_roc_auc, 4),
            "cv_std_roc_auc": round(std_cv_roc_auc, 4),
            "confusion_matrix": {
                "true_negative": cm[0][0],
                "false_positive": cm[0][1],
                "false_negative": cm[1][0],
                "true_positive": cm[1][1],
            },
            "top_features": list(self.feature_importances.items())[:8],
        }

        logger.info(
            f"Training complete! Test ROC-AUC: {roc_auc:.4f}, Accuracy: {acc:.4f}, F1: {f1:.4f}"
        )
        return self.metrics

    def save(self, model_path: Path | str | None = None, meta_path: Path | str | None = None) -> None:
        """Save model pipeline and metadata JSON to disk."""
        target_model_path = Path(model_path) if model_path else MODEL_PATH
        target_meta_path = Path(meta_path) if meta_path else METADATA_PATH

        target_model_path.parent.mkdir(parents=True, exist_ok=True)

        bundle = {
            "model": self.ensemble,
            "scaler": self.scaler,
            "feature_names": FEATURE_NAMES,
            "version": "1.0.0",
            "trained_at": self.metrics.get("trained_at"),
        }

        joblib.dump(bundle, target_model_path, compress=3)

        meta_content = {
            **self.metrics,
            "feature_importances": self.feature_importances,
            "model_path": str(target_model_path),
        }

        with open(target_meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_content, f, indent=2)

        logger.info(f"Model saved to {target_model_path} and metadata to {target_meta_path}")


if __name__ == "__main__":
    import sys
    import argparse
    from pathlib import Path

    # Ensure project root in sys.path
    root_dir = str(Path(__file__).resolve().parent.parent.parent)
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    from app.ml.dataset import BenchmarkDatasetGenerator

    parser = argparse.ArgumentParser(description="Train the Wallet Suspicion ML Model")
    parser.add_argument(
        "--samples",
        type=int,
        default=100000,
        help="Number of synthetic samples to generate for training (default: 100000)",
    )
    args = parser.parse_args()

    print("=" * 65)
    print(" Training ML Wallet Suspicion Model (app/ml/trainer.py)")
    print("=" * 65)
    generator = BenchmarkDatasetGenerator(seed=42)
    print(f"[*] Generating {args.samples:,} AML benchmark wallet transaction groups...")
    X, y, _ = generator.generate_dataset(n_samples=args.samples)

    trainer = WalletSuspicionTrainer(random_state=42)
    print("[*] Training Ensemble (RandomForest + HistGradientBoosting)...")
    metrics = trainer.train(X, y)
    trainer.save()

    print("\n" + "=" * 65)
    print(" Results:")
    print(f"   Accuracy:      {metrics['accuracy'] * 100:.2f}%")
    print(f"   ROC-AUC:       {metrics['roc_auc']:.4f}")
    print(f"   F1-Score:      {metrics['f1_score']:.4f}")
    print(f"   Saved to:      {MODEL_PATH}")
    print("=" * 65)
