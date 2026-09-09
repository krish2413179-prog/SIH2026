"""Dataset generation and loading utilities for training wallet suspicion ML models.

Supports:
1. Benchmark AML Synthetic Dataset Generation:
   Realistic simulated wallet transaction groups representing laundering typologies
   (peeling chains, mixers, structuring/smurfing, rapid pass-through, ransomware)
   and benign behaviors (retail merchants, active traders, casual holders, payroll).
2. Database Trace Extraction:
   Ingests historical trace graphs from PostgreSQL (TraceGraph / TraceJob).
3. File Ingestion:
   Loads custom transaction groups from JSON/CSV files.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from app.ml.features import FEATURE_NAMES, WalletFeatureExtractor


class BenchmarkDatasetGenerator:
    """Generates synthetic blockchain transaction groups mapped to authentic AML typologies."""

    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.extractor = WalletFeatureExtractor()

    def _generate_wallet_address(self, prefix: str = "0x") -> str:
        """Generate a random pseudo-hex address."""
        hex_chars = "".join(self.rng.choices("0123456789abcdef", k=40))
        return f"{prefix}{hex_chars}"

    # -------------------------------------------------------------------------
    # Suspicious Generators (Label = 1)
    # -------------------------------------------------------------------------

    def _gen_peeling_chain(self, target_addr: str) -> list[dict[str, Any]]:
        """Simulate a peeling chain: large inflow, rapid peel into small amount + change address.

        Lifespan is intentionally overlapping with benign wallets (1–120 days) to prevent
        the model from over-indexing on lifespan alone as the discriminating feature.
        """
        txs = []
        # Overlapping lifespan: 1–120 days (same range as some benign profiles)
        days_ago = self.rng.randint(1, 120)
        base_time = datetime.now(timezone.utc) - timedelta(days=days_ago)
        # Realistic amounts overlapping benign range (not always whale-sized)
        initial_amount = round(self.rng.uniform(0.5, 50.0), 4)

        # Inflow
        sender = self._generate_wallet_address()
        txs.append({
            "from_addr": sender,
            "to_addr": target_addr,
            "amount": initial_amount,
            "timestamp": base_time.isoformat(),
            "is_risk": False,
        })

        # Rapid peels (hops) — the key signal is the rapid timing, not the amount
        curr_time = base_time
        curr_balance = initial_amount
        peel_steps = self.rng.randint(3, 12)

        for _ in range(peel_steps):
            if curr_balance <= 0.01:
                break
            peel_amt = round(self.rng.uniform(0.005, min(1.0, curr_balance * 0.25)), 4)
            curr_balance -= peel_amt
            # Jitter: sometimes slightly longer delays to mimic realistic behaviour
            curr_time += timedelta(minutes=self.rng.randint(2, 55))  # Rapid forwarding

            txs.append({
                "from_addr": target_addr,
                "to_addr": self._generate_wallet_address(),
                "amount": peel_amt,
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })

        # Remaining balance swept to new address
        if curr_balance > 0.001:
            curr_time += timedelta(minutes=self.rng.randint(5, 30))
            txs.append({
                "from_addr": target_addr,
                "to_addr": self._generate_wallet_address(),
                "amount": round(curr_balance, 4),
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })

        return txs

    def _gen_smurfing_structuring(self, target_addr: str) -> list[dict[str, Any]]:
        """Simulate smurfing: many small round-number deposits followed by bulk cash-out.

        Lifespan overlaps with benign wallets (2–60 days) and amounts are smaller
        and more realistic to avoid gross distribution separation.
        """
        txs = []
        base_time = datetime.now(timezone.utc) - timedelta(days=self.rng.randint(2, 60))
        num_deposits = self.rng.randint(6, 25)

        # Multiple senders depositing round numbers (realistic smaller amounts)
        total_deposited = 0.0
        curr_time = base_time
        for _ in range(num_deposits):
            curr_time += timedelta(hours=self.rng.randint(1, 8))
            # Mix of round amounts + near-round amounts for realism
            base_round = float(self.rng.choice([5.0, 10.0, 20.0, 25.0, 50.0, 100.0]))
            # Occasionally add small jitter to make it less obvious
            jitter = self.rng.uniform(0.0, 0.5) if self.rng.random() < 0.3 else 0.0
            round_amt = round(base_round + jitter, 4)
            total_deposited += round_amt
            txs.append({
                "from_addr": self._generate_wallet_address(),
                "to_addr": target_addr,
                "amount": round_amt,
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })

        # Swept out in 1 or 2 burst transactions shortly after
        curr_time += timedelta(hours=self.rng.randint(1, 6))
        txs.append({
            "from_addr": target_addr,
            "to_addr": self._generate_wallet_address(),
            "amount": round(total_deposited * 0.98, 4),
            "timestamp": curr_time.isoformat(),
            "is_risk": True,
        })
        return txs

    def _gen_rapid_pass_through(self, target_addr: str) -> list[dict[str, Any]]:
        """Simulate pass-through / mule wallet: money in, money out immediately with 0 retention.

        Lifespan extended to 1–90 days so it overlaps with benign long-lived wallets.
        Key signal remains the near-zero retention and rapid forwarding timing.
        """
        txs = []
        base_time = datetime.now(timezone.utc) - timedelta(days=self.rng.randint(1, 90))
        rounds = self.rng.randint(2, 8)
        curr_time = base_time

        for _ in range(rounds):
            # Realistic amounts that overlap with DeFi trader and retail merchant
            amt = round(self.rng.uniform(0.1, 20.0), 4)
            curr_time += timedelta(hours=self.rng.randint(6, 72))
            # Inbound
            txs.append({
                "from_addr": self._generate_wallet_address(),
                "to_addr": target_addr,
                "amount": amt,
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })
            # Outbound within 2–30 minutes (near-zero retention is the key signal)
            curr_time += timedelta(minutes=self.rng.randint(2, 30))
            txs.append({
                "from_addr": target_addr,
                "to_addr": self._generate_wallet_address(),
                "amount": round(amt * self.rng.uniform(0.99, 0.999), 4),
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })
        return txs

    def _gen_mixer_interaction(self, target_addr: str) -> list[dict[str, Any]]:
        """Simulate interactions with mixer contracts / coinjoin protocols.

        Lifespan extended to 3–120 days to overlap with benign wallets.
        Key signal: high_risk_entity_exposure (is_mixer=True transaction).
        """
        txs = []
        # Overlapping lifespan with benign wallets
        base_time = datetime.now(timezone.utc) - timedelta(days=self.rng.randint(3, 120))
        curr_time = base_time
        mixer_addr = self._generate_wallet_address(prefix="0xmixer_")

        # Inflow from mixer — realistic amounts that overlap with DeFi/retail
        in_amt = round(self.rng.uniform(0.5, 15.0), 4)
        txs.append({
            "from_addr": mixer_addr,
            "to_addr": target_addr,
            "amount": in_amt,
            "timestamp": curr_time.isoformat(),
            "is_risk": True,
            "is_mixer": True,
        })

        # Disperse to multiple random addresses (fan-out is a secondary signal)
        for _ in range(self.rng.randint(4, 12)):
            curr_time += timedelta(minutes=self.rng.randint(5, 90))
            txs.append({
                "from_addr": target_addr,
                "to_addr": self._generate_wallet_address(),
                "amount": round(in_amt / self.rng.uniform(6.0, 10.0), 4),
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })
        return txs

    def _gen_ransomware_cashout(self, target_addr: str) -> list[dict[str, Any]]:
        """Simulate ransomware payment consolidation: high in-degree, night hours, burst cash-out.

        Lifespan extended to 2–90 days to overlap with benign long-lived wallets.
        Key signals: high fan-in (many unique victim senders), night_activity_ratio,
        burst_volume_ratio, and a single large cash-out to a high-risk entity.
        """
        txs = []
        # Extended lifespan — some ransomware campaigns run for months
        base_time = datetime.now(timezone.utc) - timedelta(days=self.rng.randint(2, 90))
        victims = self.rng.randint(5, 20)
        curr_time = base_time
        total_loot = 0.0

        for _ in range(victims):
            curr_time += timedelta(hours=self.rng.randint(2, 12))
            # Odd amounts (e.g. $50,000 converted to crypto)
            amt = round(self.rng.uniform(1.5, 8.0), 6)
            total_loot += amt
            txs.append({
                "from_addr": self._generate_wallet_address(),
                "to_addr": target_addr,
                "amount": amt,
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })

        # Dumped to high-risk cashout entity
        curr_time += timedelta(hours=self.rng.randint(1, 3))
        txs.append({
            "from_addr": target_addr,
            "to_addr": self._generate_wallet_address(),
            "amount": round(total_loot * 0.97, 6),
            "timestamp": curr_time.isoformat(),
            "is_risk": True,
        })
        return txs

    # -------------------------------------------------------------------------
    # Benign Generators (Label = 0)
    # -------------------------------------------------------------------------

    def _gen_casual_holder(self, target_addr: str) -> list[dict[str, Any]]:
        """Casual user: infrequent transactions, high retention, long lifespan."""
        txs = []
        start_time = datetime.now(timezone.utc) - timedelta(days=self.rng.randint(60, 365))
        in_amt = round(self.rng.uniform(0.5, 10.0), 4)

        # Deposit from CEX
        txs.append({
            "from_addr": self._generate_wallet_address(),
            "to_addr": target_addr,
            "amount": in_amt,
            "timestamp": start_time.isoformat(),
            "is_risk": False,
        })

        # A couple of small transfers months apart
        curr_time = start_time
        for _ in range(self.rng.randint(1, 4)):
            curr_time += timedelta(days=self.rng.randint(15, 60))
            if curr_time > datetime.now(timezone.utc):
                break
            txs.append({
                "from_addr": target_addr,
                "to_addr": self._generate_wallet_address(),
                "amount": round(self.rng.uniform(0.01, in_amt * 0.15), 4),
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })
        return txs

    def _gen_retail_merchant(self, target_addr: str) -> list[dict[str, Any]]:
        """Merchant: steady continuous inflows with natural variance, regular withdrawals."""
        txs = []
        base_time = datetime.now(timezone.utc) - timedelta(days=self.rng.randint(30, 90))
        num_sales = self.rng.randint(20, 60)
        curr_time = base_time
        accumulated = 0.0

        for _ in range(num_sales):
            curr_time += timedelta(hours=self.rng.randint(2, 24))
            # Natural shopping prices: e.g. 0.0245, 0.0812
            sale_amt = round(self.rng.uniform(0.005, 0.15), 5)
            accumulated += sale_amt
            txs.append({
                "from_addr": self._generate_wallet_address(),
                "to_addr": target_addr,
                "amount": sale_amt,
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })

            # Weekly settlement to owner cold wallet
            if accumulated > 0.5:
                txs.append({
                    "from_addr": target_addr,
                    "to_addr": self._generate_wallet_address(),
                    "amount": round(accumulated * 0.9, 5),
                    "timestamp": curr_time.isoformat(),
                    "is_risk": False,
                })
                accumulated *= 0.1
        return txs

    def _gen_cex_active_trader(self, target_addr: str) -> list[dict[str, Any]]:
        """Active trader: high two-way reciprocity with exchange hot wallets, regular business hours."""
        txs = []
        base_time = datetime.now(timezone.utc) - timedelta(days=self.rng.randint(20, 60))
        exchange_wallet = self._generate_wallet_address(prefix="0xbinance_")
        curr_time = base_time

        for _ in range(self.rng.randint(15, 45)):
            curr_time += timedelta(hours=self.rng.randint(6, 36))
            # Ensure transactions happen mostly during daytime (10:00 - 22:00)
            day_hour = self.rng.randint(10, 22)
            curr_time = curr_time.replace(hour=day_hour)
            amt = round(self.rng.uniform(0.2, 5.0), 4)

            # Bidirectional interaction
            if self.rng.random() < 0.5:
                txs.append({
                    "from_addr": exchange_wallet,
                    "to_addr": target_addr,
                    "amount": amt,
                    "timestamp": curr_time.isoformat(),
                    "is_risk": False,
                })
            else:
                txs.append({
                    "from_addr": target_addr,
                    "to_addr": exchange_wallet,
                    "amount": amt,
                    "timestamp": curr_time.isoformat(),
                    "is_risk": False,
                })
        return txs

    def _gen_defi_user(self, target_addr: str) -> list[dict[str, Any]]:
        """DeFi user: interactions with router contracts, cyclical swaps, high reciprocity."""
        txs = []
        base_time = datetime.now(timezone.utc) - timedelta(days=self.rng.randint(15, 45))
        dex_router = self._generate_wallet_address(prefix="0xuniswap_")
        curr_time = base_time

        for _ in range(self.rng.randint(10, 30)):
            curr_time += timedelta(hours=self.rng.randint(4, 48))
            amt_in = round(self.rng.uniform(0.1, 3.0), 4)
            amt_out = round(amt_in * self.rng.uniform(0.95, 1.05), 4)

            txs.append({
                "from_addr": target_addr,
                "to_addr": dex_router,
                "amount": amt_in,
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })
            curr_time += timedelta(minutes=self.rng.randint(1, 10))
            txs.append({
                "from_addr": dex_router,
                "to_addr": target_addr,
                "amount": amt_out,
                "timestamp": curr_time.isoformat(),
                "is_risk": False,
            })
        return txs

    # -------------------------------------------------------------------------
    # Batch Dataset Builder
    # -------------------------------------------------------------------------

    def generate_dataset(
        self,
        n_samples: int = 2000,
        suspicious_ratio: float = 0.45,
        noise_scale: float = 0.05,
    ) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
        """Generate a balanced benchmark dataset of feature vectors (X) and binary labels (y).

        Args:
            n_samples:        Total number of wallet samples.
            suspicious_ratio: Fraction of samples labelled suspicious.
            noise_scale:      Std-dev of Gaussian noise added to each normalised feature
                              (default 0.05 = 5%). This prevents the model from achieving
                              perfect separation on synthetic data and forces it to learn
                              robust behavioural signals rather than generator artefacts.

        Returns:
            X: np.ndarray of shape (n_samples, len(FEATURE_NAMES))
            y: np.ndarray of shape (n_samples,) where 1=suspicious, 0=benign
            metadata: list of dicts with address, label, profile_type, and feature dict
        """
        n_suspicious = int(n_samples * suspicious_ratio)
        n_benign = n_samples - n_suspicious

        suspicious_generators = [
            ("peeling_chain", self._gen_peeling_chain),
            ("smurfing_structuring", self._gen_smurfing_structuring),
            ("rapid_pass_through", self._gen_rapid_pass_through),
            ("mixer_interaction", self._gen_mixer_interaction),
            ("ransomware_cashout", self._gen_ransomware_cashout),
        ]

        benign_generators = [
            ("casual_holder", self._gen_casual_holder),
            ("retail_merchant", self._gen_retail_merchant),
            ("cex_active_trader", self._gen_cex_active_trader),
            ("defi_user", self._gen_defi_user),
        ]

        records: list[dict[str, Any]] = []

        # Generate suspicious samples
        for _ in range(n_suspicious):
            addr = self._generate_wallet_address()
            name, gen_func = self.rng.choice(suspicious_generators)
            txs = gen_func(addr)
            fdict = self.extractor.extract_from_transactions(addr, txs)
            records.append({
                "wallet_address": addr,
                "label": 1,
                "profile": name,
                "features": fdict,
                "tx_count": len(txs),
            })

        # Generate benign samples
        for _ in range(n_benign):
            addr = self._generate_wallet_address()
            name, gen_func = self.rng.choice(benign_generators)
            txs = gen_func(addr)
            fdict = self.extractor.extract_from_transactions(addr, txs)
            records.append({
                "wallet_address": addr,
                "label": 0,
                "profile": name,
                "features": fdict,
                "tx_count": len(txs),
            })

        # Shuffle
        self.rng.shuffle(records)

        X_rows: list[list[float]] = []
        y_vals: list[int] = []

        for rec in records:
            f = rec["features"]
            row = [float(f.get(name, 0.0)) for name in FEATURE_NAMES]
            X_rows.append(row)
            y_vals.append(rec["label"])

        X = np.array(X_rows, dtype=np.float32)
        y = np.array(y_vals, dtype=np.int32)

        # ── Gaussian noise injection ──────────────────────────────────────────
        # Normalise each feature column to [0, 1] range, add N(0, noise_scale)
        # noise, then rescale back. This prevents the ensemble from memorising
        # exact generator artefacts and forces it to learn robust signals.
        # Noise is added AFTER feature extraction so metadata stays clean.
        if noise_scale > 0.0:
            col_min = X.min(axis=0)
            col_max = X.max(axis=0)
            col_range = np.where(col_max - col_min > 0, col_max - col_min, 1.0)
            X_norm = (X - col_min) / col_range
            noise = self.np_rng.normal(0.0, noise_scale, size=X_norm.shape).astype(np.float32)
            X_norm = np.clip(X_norm + noise, 0.0, 1.0)
            X = (X_norm * col_range + col_min).astype(np.float32)
        # ─────────────────────────────────────────────────────────────────────

        return X, y, records


def load_from_json_file(file_path: str) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """Load transaction groups from a JSON file formatted as a list of wallet records.

    Expected JSON structure:
    [
      {
        "wallet_address": "0x...",
        "label": 1,
        "transactions": [ ... ]
      }
    ]
    """
    extractor = WalletFeatureExtractor()
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    X_rows = []
    y_vals = []
    metadata = []

    for item in data:
        addr = item.get("wallet_address", "")
        label = int(item.get("label", 0))
        txs = item.get("transactions", [])
        fdict = extractor.extract_from_transactions(addr, txs)
        row = [float(fdict.get(name, 0.0)) for name in FEATURE_NAMES]
        X_rows.append(row)
        y_vals.append(label)
        metadata.append({"wallet_address": addr, "label": label, "features": fdict})

    return np.array(X_rows, dtype=np.float32), np.array(y_vals, dtype=np.int32), metadata
