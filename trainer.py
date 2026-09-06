#!/usr/bin/env python3
"""Unified Machine Learning Model Trainer for Blockchain Wallet Risk Detection.

Usage:
  python trainer.py                 # Trains all models (Random Forest 0-100 Regressor + Ensemble)
  python trainer.py --risk          # Train only the 50+ feature Random Forest Regressor (0-100)
  python trainer.py --suspicion     # Train only the Ensemble Suspicion Classifier
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def train_risk_model(wallets_count: int = 50000, force_regenerate: bool = False) -> dict:
    """Train the 50+ feature Random Forest Regressor for continuous risk score (0-100)."""
    import pandas as pd
    from ml_wallet_risk.src.config import FEATURES_CSV, LABELED_WALLETS_CSV, MODEL_FILE, SCALER_FILE
    from ml_wallet_risk.src.data_collection import build_pipeline_dataset
    from ml_wallet_risk.src.model_trainer import train_and_evaluate

    print("\n" + "=" * 70)
    print(f" [1/2] Training Random Forest Regressor on {wallets_count:,} Wallets (50+ Features)")
    print("=" * 70)

    # Check if existing dataset matches the target count
    needs_gen = force_regenerate or not FEATURES_CSV.exists()
    if not needs_gen and FEATURES_CSV.exists():
        try:
            existing_count = sum(1 for _ in open(FEATURES_CSV, "r", encoding="utf-8")) - 1
            if existing_count < wallets_count:
                needs_gen = True
        except Exception:
            needs_gen = True

    if needs_gen:
        print(f"[*] Generating {wallets_count:,} labeled wallets & transaction patterns...")
        build_pipeline_dataset(wallets_count=wallets_count, txns_per_wallet=1000)

    print(f"[*] Fitting RandomForestRegressor (n_estimators=100) on {wallets_count:,} wallets...")
    metrics = train_and_evaluate()

    print("\n  Evaluation Metrics:")
    print(f"    Train R² Score:              {metrics['train_r2']:.4f}")
    print(f"    Test R² Score:               {metrics['test_r2']:.4f}  (Target: > 0.85)")
    print(f"    Test MAE (Mean Abs Error):   {metrics['test_mae']:.4f} points  (Target: < 8.0)")
    print(f"    Test RMSE:                   {metrics['test_rmse']:.4f} points")
    print(f"    5-Fold Cross-Validation R²:  {metrics['cv_mean_r2']:.4f} (+/- {metrics['cv_std_r2']:.4f})")
    print(f"    5-Fold Cross-Validation MAE: {metrics['cv_mean_mae']:.4f} points")

    print("\n  Top 5 Contributing Features:")
    for rank, item in enumerate(metrics["top_20_features"][:5], start=1):
        print(f"    {rank}. {item['feature']:<30} {item['importance']:6.4f}")

    print(f"\n  [+] Saved model:  {MODEL_FILE}")
    print(f"  [+] Saved scaler: {SCALER_FILE}")
    return metrics


def train_suspicion_model(samples: int = 50000) -> dict:
    """Train the ensemble suspicion classifier (RandomForest + HistGradientBoosting)."""
    from app.ml.dataset import BenchmarkDatasetGenerator
    from app.ml.detector import reload_detector
    from app.ml.trainer import MODEL_PATH, WalletSuspicionTrainer

    print("\n" + "=" * 70)
    print(f" [2/2] Training Wallet Suspicion Ensemble Classifier on {samples:,} Wallets")
    print("=" * 70)

    print(f"[*] Generating {samples:,} AML benchmark wallet transaction groups...")
    generator = BenchmarkDatasetGenerator(seed=42)
    X, y, _ = generator.generate_dataset(n_samples=samples)

    trainer = WalletSuspicionTrainer(random_state=42)
    print(f"[*] Fitting ensemble (Random Forest + Hist Gradient Boosting) on {samples:,} samples...")
    metrics = trainer.train(X, y)
    trainer.save()
    reload_detector()

    print("\n  Evaluation Metrics:")
    print(f"    Accuracy:                    {metrics['accuracy'] * 100:.2f}%")
    print(f"    ROC-AUC Score:               {metrics['roc_auc']:.4f}")
    print(f"    F1-Score:                    {metrics['f1_score']:.4f}")
    print(f"    Precision:                   {metrics['precision']:.4f}")
    print(f"    Recall:                      {metrics['recall']:.4f}")
    print(f"    5-Fold CV ROC-AUC:           {metrics['cv_mean_roc_auc']:.4f}")

    print(f"\n  [+] Saved model:  {MODEL_PATH}")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified ML Model Trainer for Blockchain Risk Detection"
    )
    parser.add_argument("--wallets", type=int, default=50000, help="Number of wallets for risk regressor (default: 50000)")
    parser.add_argument("--samples", type=int, default=50000, help="Samples for suspicion classifier (default: 50000)")
    parser.add_argument("--regenerate", action="store_true", help="Force re-generation of synthetic transactions")
    parser.add_argument("--risk", action="store_true", help="Train only Random Forest 0-100 Regressor")
    parser.add_argument("--suspicion", action="store_true", help="Train only Ensemble Suspicion Classifier")

    args = parser.parse_args()

    t0 = time.time()
    train_both = not (args.risk or args.suspicion)

    print("=" * 70)
    print(f"  Blockchain Intelligence — Training Pipeline on {args.wallets:,} Wallets")
    print("=" * 70)

    if train_both or args.risk:
        train_risk_model(wallets_count=args.wallets, force_regenerate=args.regenerate)

    if train_both or args.suspicion:
        train_suspicion_model(samples=args.samples)

    elapsed = time.time() - t0
    print("\n" + "=" * 70)
    print(f"  All models successfully trained on {args.wallets:,} wallets in {elapsed:.2f}s!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
