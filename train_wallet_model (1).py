#!/usr/bin/env python3
"""CLI training script for Blockchain Wallet Suspicion Detection ML Model.

Usage:
  # Train on 4,000 simulated AML transaction groups and save weights:
  python train_wallet_model.py --samples 4000 --save

  # Train on custom JSON dataset:
  python train_wallet_model.py --file my_dataset.json --save
"""

import argparse
import sys
import time

from app.ml.dataset import BenchmarkDatasetGenerator, load_from_json_file
from app.ml.detector import reload_detector
from app.ml.trainer import WalletSuspicionTrainer


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train the Machine Learning Wallet Suspicion Detection Engine."
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=3500,
        help="Number of synthetic wallet samples to generate (default: 3500)",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Optional path to a custom JSON dataset of wallet transaction groups",
    )
    parser.add_argument(
        "--cv",
        type=int,
        default=5,
        help="Cross-validation folds (default: 5)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        default=True,
        help="Save trained model bundle and metadata to disk",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )

    args = parser.parse_args()

    print("=" * 70)
    print(" Blockchain Intelligence — ML Wallet Suspicion Training Pipeline")
    print("=" * 70)

    t0 = time.time()

    if args.file:
        print(f"[*] Loading dataset from file: {args.file}...")
        X, y, records = load_from_json_file(args.file)
        print(f"[+] Loaded {len(X)} samples with {X.shape[1]} features.")
    else:
        print(f"[*] Generating benchmark AML dataset ({args.samples} wallet transaction groups)...")
        generator = BenchmarkDatasetGenerator(seed=args.seed)
        X, y, records = generator.generate_dataset(n_samples=args.samples)
        suspicious_cnt = int((y == 1).sum())
        benign_cnt = int((y == 0).sum())
        print(f"[+] Generated {len(X)} samples ({suspicious_cnt} suspicious, {benign_cnt} benign).")
        print(f"[+] Extracted 25 behavioral and graph features per wallet.")

    print("\n[*] Initializing ensemble trainer (Random Forest + Hist Gradient Boosting)...")
    trainer = WalletSuspicionTrainer(random_state=args.seed)

    print(f"[*] Executing {args.cv}-fold stratified cross-validation and training on holdout...")
    metrics = trainer.train(X, y, test_size=0.2, cv_folds=args.cv)

    elapsed = time.time() - t0

    print("\n" + "=" * 70)
    print(" Model Training & Validation Results")
    print("=" * 70)
    print(f"  Accuracy:                 {metrics['accuracy'] * 100:.2f}%")
    print(f"  ROC-AUC Score:            {metrics['roc_auc']:.4f}")
    print(f"  Precision:                {metrics['precision']:.4f}")
    print(f"  Recall:                   {metrics['recall']:.4f}")
    print(f"  F1-Score:                 {metrics['f1_score']:.4f}")
    print(f"  5-Fold Mean CV ROC-AUC:   {metrics['cv_mean_roc_auc']:.4f} (+/- {metrics['cv_std_roc_auc']:.4f})")
    print(f"  Training Time:            {elapsed:.2f} seconds")

    cm = metrics["confusion_matrix"]
    print("\n  Confusion Matrix (Holdout Set):")
    print(f"    True Negatives (Benign):        {cm['true_negative']}")
    print(f"    False Positives:                {cm['false_positive']}")
    print(f"    False Negatives:                {cm['false_negative']}")
    print(f"    True Positives (Suspicious):    {cm['true_positive']}")

    print("\n  Top Contributing Behavioral Features:")
    for rank, (feat, imp) in enumerate(metrics["top_features"], start=1):
        bar = "#" * int(imp * 80)
        print(f"    {rank:2d}. {feat:<28} {imp:6.3f} | {bar}")

    if args.save:
        print("\n[*] Serializing model artifacts to disk...")
        trainer.save()
        reload_detector()
        print("[+] Model saved successfully to app/ml/artifacts/wallet_suspicion_model.joblib")
        print("[+] Metadata saved to app/ml/artifacts/model_metadata.json")

    print("\n[+] Training complete! Model is ready for inference.")
    print("=" * 70)


if __name__ == "__main__":
    main()
