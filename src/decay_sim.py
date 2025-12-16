"""
src/decay_sim.py

LETF decay simulation utilities.

Provides:
- simulate_lef_decay: bootstrap Monte Carlo of T-day LETF returns (path-dependent).
- estimate_letf_decay_analytic: quick analytic approximation based on volatility.
- helpers to compute returns from price series and a small CLI for demo.

Notes:
- LETF daily factor = 1 + leverage * underlying_return(%) as decimal (e.g., 0.01).
- Output statistics are returned as a dict with mean/median/percentiles and optional raw results.
"""

from typing import Any, Dict, Optional
import numpy as np
import pandas as pd


def compute_returns_from_prices(prices: pd.Series) -> np.ndarray:
    """
    Compute simple daily returns from a price series.

    Args:
        prices: pd.Series of prices ordered by date ascending.

    Returns:
        numpy array of daily returns as decimals (e.g., 0.01 for +1%).
    """
    # Drop NaNs and ensure monotonic index order
    p = prices.dropna().astype(float)
    returns = p.pct_change().dropna().to_numpy(dtype=float)
    return returns


def simulate_lef_decay(
    underlying_returns: np.ndarray,
    leverage: float,
    window: int,
    trials: int = 20000,
    seed: int = 42,
    return_results: bool = False,
) -> Dict[str, Any]:
    """
    Monte Carlo (bootstrap) simulation of LETF T-day returns.

    The LETF daily return for underlying return r_i is: factor_i = 1 + leverage * r_i
    The T-day LETF return = product(factor_i) - 1

    Args:
        underlying_returns: 1-D numpy array of historical daily underlying returns (decimal).
        leverage: leverage factor (e.g., 3.0 for 3x; -3.0 for -3x)
        window: holding horizon in trading days (T).
        trials: number of bootstrap trials to run.
        seed: RNG seed for determinism.
        return_results: if True, include the raw results array in the output dict.

    Returns:
        dict containing summary statistics:
            - mean, median, p10, p25, p75, p90, worst, best, trials, window
            - optionally 'results' (numpy array) if return_results is True
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    n = len(underlying_returns)
    if n < window:
        raise ValueError("underlying_returns length must be at least window")

    rng = np.random.default_rng(seed)
    # bootstrap starting indices
    starts = rng.integers(low=0, high=n - window + 1, size=trials)
    results = np.empty(trials, dtype=float)

    for i, s in enumerate(starts):
        slice_r = underlying_returns[s : s + window]
        # daily LETF factor
        factors = 1.0 + leverage * slice_r
        # Guard: extremely negative daily factors can flip sign or make product unbounded.
        # We clip factor lower bound to -0.999 to avoid zeros or -inf when multiplying.
        # This keeps extreme simulated paths finite; adjust policy as needed.
        factors = np.maximum(factors, -0.999)
        cumulative = np.prod(factors)
        results[i] = cumulative - 1.0

    stats = {
        "mean": float(np.mean(results)),
        "median": float(np.median(results)),
        "p10": float(np.percentile(results, 10)),
        "p25": float(np.percentile(results, 25)),
        "p75": float(np.percentile(results, 75)),
        "p90": float(np.percentile(results, 90)),
        "worst": float(np.min(results)),
        "best": float(np.max(results)),
        "trials": int(trials),
        "window": int(window),
        "leverage": float(leverage),
    }
    if return_results:
        stats["results"] = results
    return stats


def estimate_letf_decay_analytic(
    leverage: float, underlying_vol_annual: float, horizon_days: int, trading_days: int = 252
) -> float:
    """
    Analytical approximation of expected LETF decay fraction over a horizon.

    Uses the continuous approximation:
        expected_factor ≈ exp( (x - x^2) * sigma^2 * T / 2 )

    For x = leverage, sigma = annual volatility, T = horizon_years.

    Returns:
        decay_fraction (positive number): approximate expected fractional decay (e.g., 0.003 -> 0.3%)
    """
    if underlying_vol_annual < 0:
        raise ValueError("underlying_vol_annual must be non-negative")
    x = leverage
    sigma = underlying_vol_annual
    T = float(horizon_days) / trading_days
    # If x - x^2 is positive (which happens for leverage between 0 and 1), factor>1;
    # for leverage >=2 or negative leverage, x-x^2 is typically negative yielding decay.
    exponent = (x - x * x) * (sigma ** 2) * T / 2.0
    expected_factor = np.exp(exponent)
    decay_fraction = max(0.0, 1.0 - expected_factor) if expected_factor < 1.0 else 0.0
    return float(decay_fraction)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="LETF decay simulator demo")
    parser.add_argument("--parquet", help="Path to parquet file with columns ['date','ticker','adj_close']", default=None)
    parser.add_argument("--ticker", help="Ticker to analyze (e.g., SPY)", default="SPY")
    parser.add_argument("--leverage", help="LETF leverage (e.g., 3.0 or -3.0)", type=float, default=3.0)
    parser.add_argument("--window", help="Holding window in days", type=int, default=5)
    parser.add_argument("--trials", help="Monte Carlo trials", type=int, default=20000)
    parser.add_argument("--seed", help="RNG seed", type=int, default=42)
    args = parser.parse_args()

    # Demo: if no parquet provided, synthesize returns
    if args.parquet is None:
        print("No parquet provided — generating synthetic returns for demo.")
        rng = np.random.default_rng(args.seed)
        returns = rng.normal(0, 0.01, 2000)
    else:
        try:
            df = pd.read_parquet(args.parquet)
        except Exception as e:
            print(f"Failed to read parquet: {e}", file=sys.stderr)
            sys.exit(2)
        df = df.sort_values("date")
        if args.ticker:
            df = df[df["ticker"] == args.ticker]
        if df.empty:
            print(f"No data for ticker {args.ticker}", file=sys.stderr)
            sys.exit(3)
        returns = compute_returns_from_prices(df["adj_close"])

    res = simulate_lef_decay(
        underlying_returns=returns,
        leverage=args.leverage,
        window=args.window,
        trials=args.trials,
        seed=args.seed,
    )

    analytic = estimate_letf_decay_analytic(args.leverage, underlying_vol_annual=np.std(returns) * np.sqrt(252), horizon_days=args.window)

    print("Simulation summary:")
    print(f"Leverage: {res['leverage']}, Window (days): {res['window']}, Trials: {res['trials']}")
    print(f"Mean return: {res['mean']:.6f}, Median: {res['median']:.6f}")
    print(f"P10: {res['p10']:.6f}, P90: {res['p90']:.6f}")
    print(f"Worst: {res['worst']:.6f}, Best: {res['best']:.6f}")
    print(f"Analytic estimated decay fraction: {analytic:.6%}")
