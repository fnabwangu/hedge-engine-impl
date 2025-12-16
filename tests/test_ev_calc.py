# tests/test_ev_calc.py

import pytest
from src.ev_calc import compute_ev, compute_t_max


def test_ev_positive_expected_value_passes_viability():
    signal = {
        "p_success": 0.8,
        "p_confidence": 0.8,
        "expected_delta": {"fav": 0.10, "neutral": 0.0, "unfav": -0.05},
        "horizon_days": 5,
        "suggested_instrument": {"type": "LETF", "ticker": "SSO", "leverage": 3},
    }
    # decay_stats mean negative implies positive drag (0.01)
    decay_stats = {"mean": -0.01}
    res = compute_ev(signal, decay_stats, trading_costs=0.0005, slippage=0.0005, safety_margin=0.01)

    assert "ev_gross" in res and "ev_net" in res and "viability_pass" in res
    assert res["ev_gross"] > 0.0
    assert res["letf_decay"] == pytest.approx(0.01, rel=1e-6)
    assert res["ev_net"] > res["letf_decay"]
    assert res["viability_pass"] is True


def test_ev_low_confidence_blocks_viability_even_if_ev_positive():
    signal = {
        "p_success": 0.8,
        "p_confidence": 0.6,  # below 0.7 threshold
        "expected_delta": {"fav": 0.10, "neutral": 0.0, "unfav": -0.05},
        "horizon_days": 5,
        "suggested_instrument": {"type": "LETF", "ticker": "SSO", "leverage": 3},
    }
    decay_stats = {"mean": -0.01}
    res = compute_ev(signal, decay_stats, trading_costs=0.0005, slippage=0.0005, safety_margin=0.01)

    # Even though ev_net may be positive, low confidence should cause human-review (viability False)
    assert res["ev_net"] > 0.0
    assert res["p_confidence"] == pytest.approx(0.6)
    assert res["viability_pass"] is False


def test_ev_negative_expected_value_fails_viability():
    signal = {
        "p_success": 0.1,
        "p_confidence": 0.9,
        "expected_delta": {"fav": 0.02, "neutral": 0.0, "unfav": -0.10},
        "horizon_days": 5,
        "suggested_instrument": {"type": "ETF", "ticker": "SPY", "leverage": 1},
    }
    # no decay
    decay_stats = {"mean": 0.0}
    res = compute_ev(signal, decay_stats, trading_costs=0.0005, slippage=0.0005, safety_margin=0.01)

    assert res["ev_gross"] < 0.0
    assert res["ev_net"] < 0.0
    assert res["viability_pass"] is False


def test_compute_t_max_behaviour():
    # For 3x and 20% vol baseline we expect ~5 days
    t3 = compute_t_max(3.0, 0.20)
    assert isinstance(t3, int)
    assert t3 == 5

    # For 2x and 20% vol baseline we expect ~10 days
    t2 = compute_t_max(2.0, 0.20)
    assert t2 == 10

    # For leverage 1 (or <2) expect larger default
    t1 = compute_t_max(1.0, 0.20)
    assert t1 >= 30 or t1 == 30  # heuristic returns 30 for baseline

    # Very high vol results in smaller T_max but at least 1
    t_highvol = compute_t_max(3.0, 1.0)  # 100% annual vol
    assert t_highvol >= 1
    assert t_highvol <= 5  # should be smaller than baseline 5 for 20% vol
