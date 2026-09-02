"""Unit tests for app/risk/scorer.py.

Covers:
  - compute_risk_score: formula correctness, boundary values, clamping
  - classify_risk_band: all band boundaries (39=low, 40=medium, 69=medium, 70=high)
  - get_vasp_risk_weight: all known categories and unknown fallback

Requirements: 8.1, 8.2, 8.3
"""

from __future__ import annotations

import pytest

from app.risk.scorer import (
    VASP_RISK_TIERS,
    classify_risk_band,
    compute_risk_score,
    get_vasp_risk_weight,
)


# ---------------------------------------------------------------------------
# compute_risk_score — formula correctness
# ---------------------------------------------------------------------------


class TestComputeRiskScore:
    def test_all_zeros_returns_0(self):
        """Zero inputs → score 0."""
        assert compute_risk_score(0, 0, 0, 0, 0) == 0

    def test_all_ones_returns_100(self):
        """Maximum inputs → score 100."""
        assert compute_risk_score(1, 1, 1, 1, 1) == 100

    def test_weighted_formula_direct_exposure_only(self):
        """Only direct_exposure=1, rest 0 → round(0.35 * 100) = 35."""
        assert compute_risk_score(1.0, 0, 0, 0, 0) == 35

    def test_weighted_formula_indirect_exposure_only(self):
        """Only indirect_exposure=1, rest 0 → round(0.20 * 100) = 20."""
        assert compute_risk_score(0, 1.0, 0, 0, 0) == 20

    def test_weighted_formula_vasp_risk_only(self):
        """Only vasp_risk_category=1, rest 0 → round(0.20 * 100) = 20."""
        assert compute_risk_score(0, 0, 1.0, 0, 0) == 20

    def test_weighted_formula_typology_only(self):
        """Only typology_flags=1, rest 0 → round(0.15 * 100) = 15."""
        assert compute_risk_score(0, 0, 0, 1.0, 0) == 15

    def test_weighted_formula_volume_anomaly_only(self):
        """Only volume_anomaly=1, rest 0 → round(0.10 * 100) = 10."""
        assert compute_risk_score(0, 0, 0, 0, 1.0) == 10

    def test_weights_sum_to_100(self):
        """Sanity check: all weights sum to 1.0 → score 100 when all inputs are 1."""
        # 0.35 + 0.20 + 0.20 + 0.15 + 0.10 = 1.0
        assert compute_risk_score(1, 1, 1, 1, 1) == 100

    def test_known_mixed_inputs(self):
        """Manual calculation: (0.35*0.5 + 0.20*0.5 + 0.20*0.5 + 0.15*0.5 + 0.10*0.5) * 100 = 50."""
        assert compute_risk_score(0.5, 0.5, 0.5, 0.5, 0.5) == 50

    def test_known_asymmetric_inputs(self):
        """de=1, ie=0.5, vc=0, tf=0, va=0 → round((0.35 + 0.10) * 100) = 45."""
        expected = round((0.35 * 1.0 + 0.20 * 0.5 + 0.20 * 0.0 + 0.15 * 0.0 + 0.10 * 0.0) * 100)
        assert compute_risk_score(1.0, 0.5, 0.0, 0.0, 0.0) == expected

    def test_returns_int(self):
        """Return type must be int."""
        result = compute_risk_score(0.3, 0.2, 0.1, 0.05, 0.05)
        assert isinstance(result, int)

    # --- Clamping ---

    def test_clamps_inputs_above_1(self):
        """Inputs > 1 are clamped to 1 → same as all-ones → 100."""
        assert compute_risk_score(2.0, 5.0, 99.9, 3.0, 10.0) == 100

    def test_clamps_negative_inputs(self):
        """Negative inputs are clamped to 0 → same as all-zeros → 0."""
        assert compute_risk_score(-1.0, -0.5, -100.0, -0.1, -99.0) == 0

    def test_clamps_mixed_out_of_range(self):
        """Mix of in-range and clamped inputs behaves like all inputs clamped to [0,1]."""
        # direct_exposure=-0.5 → 0; rest valid → same as compute_risk_score(0, 0.5, 0.5, 0.5, 0.5)
        expected = compute_risk_score(0.0, 0.5, 0.5, 0.5, 0.5)
        assert compute_risk_score(-0.5, 0.5, 0.5, 0.5, 0.5) == expected

    # --- Result is always in [0, 100] ---

    def test_result_never_below_0(self):
        assert compute_risk_score(-999, -999, -999, -999, -999) >= 0

    def test_result_never_above_100(self):
        assert compute_risk_score(999, 999, 999, 999, 999) <= 100


# ---------------------------------------------------------------------------
# classify_risk_band — boundary values
# ---------------------------------------------------------------------------


class TestClassifyRiskBand:
    # Low band: 0-39
    def test_score_0_is_low(self):
        assert classify_risk_band(0) == "low"

    def test_score_1_is_low(self):
        assert classify_risk_band(1) == "low"

    def test_score_39_is_low(self):
        assert classify_risk_band(39) == "low"

    # Medium band boundary: 40-69
    def test_score_40_is_medium(self):
        assert classify_risk_band(40) == "medium"

    def test_score_41_is_medium(self):
        assert classify_risk_band(41) == "medium"

    def test_score_55_is_medium(self):
        assert classify_risk_band(55) == "medium"

    def test_score_69_is_medium(self):
        assert classify_risk_band(69) == "medium"

    # High band boundary: 70-100
    def test_score_70_is_high(self):
        assert classify_risk_band(70) == "high"

    def test_score_71_is_high(self):
        assert classify_risk_band(71) == "high"

    def test_score_99_is_high(self):
        assert classify_risk_band(99) == "high"

    def test_score_100_is_high(self):
        assert classify_risk_band(100) == "high"

    # Return type
    def test_returns_string(self):
        for score in [0, 39, 40, 69, 70, 100]:
            result = classify_risk_band(score)
            assert isinstance(result, str)
            assert result in ("low", "medium", "high")

    # Parametrized boundary sweep
    @pytest.mark.parametrize("score,expected_band", [
        (0, "low"),
        (39, "low"),
        (40, "medium"),
        (69, "medium"),
        (70, "high"),
        (100, "high"),
    ])
    def test_band_boundaries(self, score: int, expected_band: str):
        assert classify_risk_band(score) == expected_band


# ---------------------------------------------------------------------------
# get_vasp_risk_weight — known categories and unknown fallback
# ---------------------------------------------------------------------------


class TestGetVaspRiskWeight:
    @pytest.mark.parametrize("category,expected_weight", [
        ("CEX", 0.1),
        ("DEX", 0.3),
        ("mixer", 0.9),
        ("bridge", 0.5),
        ("darknet", 1.0),
        ("other", 0.2),
    ])
    def test_known_categories(self, category: str, expected_weight: float):
        """All defined VASP categories return their documented weight."""
        assert get_vasp_risk_weight(category) == pytest.approx(expected_weight)

    def test_unknown_category_falls_back_to_0_2(self):
        """Unrecognised categories fall back to 0.2 (the 'other' weight)."""
        assert get_vasp_risk_weight("unknown_type") == pytest.approx(0.2)

    def test_empty_string_falls_back(self):
        assert get_vasp_risk_weight("") == pytest.approx(0.2)

    def test_case_sensitive_lowercase_mixer(self):
        """Lookup is case-sensitive; 'Mixer' ≠ 'mixer' → fallback."""
        assert get_vasp_risk_weight("Mixer") == pytest.approx(0.2)

    def test_case_sensitive_uppercase_cex(self):
        """'cex' (wrong case) falls back since table key is 'CEX'."""
        assert get_vasp_risk_weight("cex") == pytest.approx(0.2)

    def test_returns_float(self):
        """Return type is always float."""
        for cat in list(VASP_RISK_TIERS.keys()) + ["random_unknown"]:
            assert isinstance(get_vasp_risk_weight(cat), float)

    def test_all_known_weights_in_0_1_range(self):
        """Every defined weight is within [0.0, 1.0]."""
        for category in VASP_RISK_TIERS:
            weight = get_vasp_risk_weight(category)
            assert 0.0 <= weight <= 1.0, f"{category!r} weight {weight} out of range"

    def test_darknet_is_maximum_risk(self):
        assert get_vasp_risk_weight("darknet") == pytest.approx(1.0)

    def test_cex_is_lowest_known_risk(self):
        assert get_vasp_risk_weight("CEX") == pytest.approx(0.1)
