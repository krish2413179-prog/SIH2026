"""Risk scoring functions for the Blockchain Intelligence & VASP Attribution Engine.

Implements the weighted risk score formula and band classification described
in the design document, Section 8.

Requirements: 8.1, 8.2, 8.3

============================================================
RISK SCORING FORMULA (canonical reference)
============================================================

    Risk Score = round(
        (
            0.35 * direct_exposure
          + 0.20 * indirect_exposure
          + 0.20 * vasp_risk_category
          + 0.15 * typology_flags
          + 0.10 * volume_anomaly
        ) * 100
    )

All factor inputs are normalised to [0.0, 1.0] before the formula is applied.
The final score is an integer in [0, 100].

------------------------------------------------------------
Factor weights
------------------------------------------------------------

  direct_exposure    (weight 0.35)
      Ratio of flagged direct neighbours of the seed address.
      "Flagged" means the node is tagged as mixer, sanctioned,
      darknet, or scam.  Value = flagged_direct / total_direct,
      or 0.0 if the seed has no direct neighbours.

  indirect_exposure  (weight 0.20)
      Same ratio but computed over ALL nodes within 3 hops of
      the seed (excluding the seed itself).

  vasp_risk_category (weight 0.20)
      Risk tier of the nearest attributed VASP in the graph.
      Tier lookup (see VASP_RISK_TIERS below):
          CEX      → 0.1  (regulated exchange, lowest risk)
          DEX      → 0.3  (medium-low)
          bridge   → 0.5  (medium)
          mixer    → 0.9  (very high)
          darknet  → 1.0  (maximum risk)
      Defaults to 0.2 for any unrecognised category ("other").

  typology_flags     (weight 0.15)
      Normalised count of active laundering typology flags
      (peel chain, smurfing, layering, fan-out, fan-in, etc.).
      Value = active_flag_count / total_possible_flags, clamped
      to [0, 1].

  volume_anomaly     (weight 0.10)
      Z-score normalised transaction velocity for the seed
      wallet, clamped to [0, 1].  A value of 1.0 means the
      velocity is ≥ 3 standard deviations above the historical
      mean for the chain.

------------------------------------------------------------
Band thresholds
------------------------------------------------------------

    Low    :  0 – 39
    Medium : 40 – 69
    High   : 70 – 100

------------------------------------------------------------
Automatic override
------------------------------------------------------------

    If any sanctioned or darknet address is present anywhere
    in the transaction graph the score is forced to ≥ 90,
    regardless of the weighted formula result.  This ensures
    regulatory-mandated immediate escalation whenever OFAC /
    darknet exposure is detected.

============================================================
"""

from __future__ import annotations

from typing import Literal

RiskBand = Literal["low", "medium", "high"]

# ---------------------------------------------------------------------------
# Core scoring functions
# ---------------------------------------------------------------------------


def compute_risk_score(
    direct_exposure: float,    # 0-1: ratio of flagged direct neighbors
    indirect_exposure: float,  # 0-1: within 3 hops
    vasp_risk_category: float, # 0-1: from VASP risk tier
    typology_flags: float,     # 0-1: normalized count of active typology flags
    volume_anomaly: float,     # 0-1: z-score normalized
) -> int:
    """Compute integer risk score in [0, 100].

    Formula: round((0.35*de + 0.20*ie + 0.20*vc + 0.15*tf + 0.10*va) * 100)

    All inputs are clamped to [0.0, 1.0] before scoring so out-of-range
    values never produce a score outside [0, 100].

    Requirements: 8.1, 8.2
    """
    # Clamp each input to [0.0, 1.0]
    de = max(0.0, min(1.0, direct_exposure))
    ie = max(0.0, min(1.0, indirect_exposure))
    vc = max(0.0, min(1.0, vasp_risk_category))
    tf = max(0.0, min(1.0, typology_flags))
    va = max(0.0, min(1.0, volume_anomaly))

    raw = (
        0.35 * de
        + 0.20 * ie
        + 0.20 * vc
        + 0.15 * tf
        + 0.10 * va
    ) * 100

    # Clamp the result defensively (floating-point rounding can push slightly outside)
    return max(0, min(100, round(raw)))


def classify_risk_band(score: int) -> RiskBand:
    """Classify a risk score into a named band.

    Band boundaries (inclusive):
      Low:    0 – 39
      Medium: 40 – 69
      High:   70 – 100

    Requirement: 8.3
    """
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# VASP risk tier lookup table
# ---------------------------------------------------------------------------

# Maps VASP category strings to a float risk weight in [0.0, 1.0].
# Used to populate the ``vasp_risk_category`` parameter of ``compute_risk_score``.
VASP_RISK_TIERS: dict[str, float] = {
    "CEX": 0.1,       # Low risk — regulated exchange
    "DEX": 0.3,       # Medium-low
    "mixer": 0.9,     # Very high risk
    "bridge": 0.5,    # Medium
    "darknet": 1.0,   # Maximum risk
    "other": 0.2,
}


def get_vasp_risk_weight(category: str) -> float:
    """Return the risk weight for a VASP category.

    Falls back to 0.2 (the weight for the "other" category) for any
    unrecognised category string so callers never receive ``None``.
    """
    return VASP_RISK_TIERS.get(category, VASP_RISK_TIERS["other"])
