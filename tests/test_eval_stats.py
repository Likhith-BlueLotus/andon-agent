"""eval/stats.py on hand-made examples (EVAL_PLAN §4)."""

import math

import pytest

from eval import stats


def test_wilson_known_values():
    iv = stats.wilson(8, 10)
    assert iv.p == 0.8
    assert iv.lo == pytest.approx(0.4902, abs=1e-3)
    assert iv.hi == pytest.approx(0.9433, abs=1e-3)


def test_wilson_edges_and_zero_n():
    z = stats.wilson(0, 10)
    assert z.lo == 0.0 and z.hi == pytest.approx(0.2775, abs=1e-3)
    o = stats.wilson(10, 10)
    assert o.hi == pytest.approx(1.0) and o.lo == pytest.approx(0.7225, abs=1e-3)
    e = stats.wilson(0, 0)
    assert e.p is None and e.lo is None and str(e) == "n/a"
    with pytest.raises(ValueError):
        stats.wilson(5, 3)


def test_wilson_small_n_is_wide():
    iv = stats.wilson(10, 17)  # R-set sized
    assert iv.hi - iv.lo > 0.35


def test_mcnemar_exact_values():
    m = stats.mcnemar_exact(5, 1)
    assert m.p == pytest.approx(2 * (1 + 6) / 64)
    assert stats.mcnemar_exact(0, 8).p == pytest.approx(2 / 256)
    assert stats.mcnemar_exact(0, 0).p == 1.0


def test_mcnemar_non_significant_case_is_not_significant():
    m = stats.mcnemar_exact(6, 4, both_right=40, both_wrong=10)
    assert m.p > 0.05
    assert m.p == pytest.approx(0.7539, abs=1e-3)
    assert m.n == 60


def test_mcnemar_symmetry_and_cap():
    assert stats.mcnemar_exact(3, 3).p == 1.0
    assert stats.mcnemar_exact(2, 9).p == stats.mcnemar_exact(9, 2).p


def test_paired_counts_discordant():
    a = {"S1": True, "S2": True, "S3": False, "S4": False, "S5": True}
    b = {"S1": True, "S2": False, "S3": True, "S4": False, "S6": True}
    m = stats.paired(a, b)  # S5/S6 are not in both
    assert (m.a_only, m.b_only, m.both_right, m.both_wrong) == (1, 1, 1, 1)
    assert m.p == 1.0


def test_brier_and_reliability():
    assert stats.brier([0.9, 0.1], [True, False]) == pytest.approx(0.01)
    assert stats.brier([1.0, 1.0], [False, False]) == 1.0
    assert stats.brier([], []) is None
    bins = stats.reliability_bins([0.05, 0.15, 0.55, 0.95, 1.0], [False, False, True, True, True])
    assert [b["n"] for b in bins] == [2, 0, 1, 0, 2]
    assert bins[0]["accuracy"] == 0.0 and bins[4]["accuracy"] == 1.0
    assert bins[1]["accuracy"] is None
    assert stats.expected_calibration_error(bins) == pytest.approx((2 * 0.1 + 0.45 + 2 * 0.025) / 5)
    with pytest.raises(ValueError):
        stats.reliability_bins([1.2], [True])


def test_percentiles_and_spread():
    assert stats.median([3, 1, 2]) == 2
    assert stats.percentile([1, 2, 3, 4], 95) == pytest.approx(3.85)
    assert stats.median([]) is None
    sp = stats.spread([0.5, 0.7, 0.6])
    assert sp["range"] == pytest.approx(0.2) and math.isclose(sp["mean"], 0.6)
