# tests/test_decay_sim.py

import numpy as np
import pytest

from src.decay_sim import simulate_lef_decay, estimate_letf_decay_analytic


def test_decay_sim_basic():
    rng = np.random.default_rng(12345)
    # synthetic underlying returns with modest vol
    underlying = rng.normal(0.0, 0.01, 1000)
    stats = simulate_lef_decay(underlying_returns=underlying, leverage=3.0, window=5, trials=500, seed=42)

    # basic shape/keys
    assert isinstance(stats, dict)
    assert stats["trials"] == 500
    assert "mean" in stats and "median" in stats and "worst" in stats and "best" in stats

    # numeric sanity
    assert np.isfinite(stats["mean"])
    assert stats["worst"] <= stats["best"]


def test_decay_sim_zero_vol():
    # If underlying never moves, LETF should produce zero multi-day return (no path-dependence effect)
    underlying = np.zeros(200)
    stats = simulate_lef_decay(underlying_returns=underlying, leverage=3.0, window=10, trials=100, seed=1)

    # All simulated returns should be exactly zero (or extremely close)
    assert pytest.approx(0.0, abs=1e-12) == stats["mean"]
    assert pytest.approx(0.0, abs=1e-12) == stats["median"]
    assert pytest.approx(0.0, abs=1e-12) == stats["worst"]
    assert pytest.approx(0.0, abs=1e-12) == stats["best"]


def test_decay_sim_window_too_large_raises():
    rng = np.random.default_rng(1)
    underlying = rng.normal(0, 0.01, 10)
    with pytest.raises(ValueError):
        simulate_lef_decay(underlying_returns=underlying, leverage=2.0, window=20, trials=100)


def test_estimate_letf_decay_analytic_behavior():
    # analytic estimator should return a non-negative float and scale with vol/horizon
    decay_small = estimate_letf_decay_analytic(leverage=3.0, underlying_vol_annual=0.10, horizon_days=5)
    decay_large = estimate_letf_decay_analytic(leverage=3.0, underlying_vol_annual=0.30, horizon_days=20)

    assert isinstance(decay_small, float)
    assert isinstance(decay_large, float)
    assert decay_small >= 0.0
    assert decay_large >= 0.0
    # larger vol and longer horizon should generally produce greater decay (weak monotonicity)
    assert decay_large >= decay_small
