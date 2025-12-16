"""
src/risk_engine.py

Risk management utilities for Hedge Engine.

This module provides small, deterministic, auditable functions used by the
Decision Engine for volatility-targeting (position scaling), simple VaR
estimators (parametric and historical), stop-loss calculations, and
drawdown/emergency triggers.

The implementations below are intentionally straightforward and conservative:
they favor clarity and auditability over exotic statistical tricks.
"""

from typing import Tuple, Optional, Sequence, Dict, Any
import math
import numpy as np
import pandas as pd


def compute_annualized_vol(returns: np.ndarray, trading_days: int = 252) -> float:
    """
    Compute annualized volatility from daily returns.

    Args:
        returns: 1-D array of daily returns (decimals, e.g., 0.01 = 1%).
        trading_days: trading days per year (default 252).

    Returns:
        annualized volatility (decimal).
    """
    if returns is None or len(returns) == 0:
        return 0.0
    # Use sample std (ddof=1) to be conventional for historical vol
    daily_std = float(np.std(returns, ddof=1))
    return daily_std * math.sqrt(trading_days)


def compute_scale_factor(
    target_annual_vol: float,
    returns: np.ndarray,
    max_scale: float = 2.0,
    min_scale: float = 0.3,
    trading_days: int = 252,
) -> Tuple[float, float]:
    """
    Compute a volatility-based scale factor to size positions.

    The scale factor = target_vol / recent_vol (clamped between min_scale and
    max_scale). Recent vol is computed from the provided returns array.

    Args:
        target_annual_vol: desired annualized vol (decimal, e.g., 0.10).
        returns: 1-D numpy array of recent daily portfolio (or instrument) returns.
        max_scale: maximum multiplier (avoid blowing up).
        min_scale: minimum multiplier (avoid zeroing out).
        trading_days: days per year for annualization.

    Returns:
        Tuple(scale_factor, recent_annual_vol)
    """
    recent_vol = compute_annualized_vol(returns, trading_days=trading_days)
    if recent_vol <= 0:
        # If no volatility observed, return neutral scaling of 1.0
        return 1.0, recent_vol
    scale = float(target_annual_vol) / recent_vol
    scale = max(min_scale, min(max_scale, scale))
    return scale, recent_vol


def _inverse_normal_cdf(p: float) -> float:
    """
    Approximate inverse CDF (quantile) for standard normal distribution.

    Uses a rational approximation (Acklam / Beasley-Springer / Moro-style).
    Valid for 0 < p < 1. Returns z such that P(Z <= z) = p for Z ~ N(0,1).

    This avoids external dependencies like scipy while providing adequate
    precision for risk gating.
    """
    if p <= 0.0 or p >= 1.0:
        raise ValueError("p must be in (0,1)")

    # Coefficients for approximation
    a = [
        -3.969683028665376e+01,
        2.209460984245205e+02,
        -2.759285104469687e+02,
        1.383577518672690e+02,
        -3.066479806614716e+01,
        2.506628277459239e+00,
    ]
    b = [
        -5.447609879822406e+01,
        1.615858368580409e+02,
        -1.556989798598866e+02,
        6.680131188771972e+01,
        -1.328068155288572e+01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e+00,
        -2.549732539343734e+00,
        4.374664141464968e+00,
        2.938163982698783e+00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e+00,
        3.754408661907416e+00,
    ]

    # Define break-points
    plow = 0.02425
    phigh = 1 - plow

    if p < plow:
        # Rational approximation for lower region
        q = math.sqrt(-2 * math.log(p))
        num = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        den = ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        z = -num / den
    elif p > phigh:
        # Rational approximation for upper region
        q = math.sqrt(-2 * math.log(1 - p))
        num = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        den = ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        z = num / den
    else:
        # Rational approximation for central region
        q = p - 0.5
        r = q * q
        num = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        den = (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        z = q * num / den

    return float(z)


def parametric_var(portfolio_returns: np.ndarray, alpha: float = 0.01) -> float:
    """
    Compute a 1-day parametric (variance-covariance) VaR for a portfolio return series.

    Uses a normal distribution approximation:
        VaR_alpha = -(mu + z_alpha * sigma)

    Args:
        portfolio_returns: 1-D numpy array of historical portfolio daily returns.
        alpha: tail probability (e.g., 0.01 for 99% VaR).

    Returns:
        Positive VaR number (as fraction of capital). For example 0.02 => 2% 1-day VaR.
    """
    if portfolio_returns is None or len(portfolio_returns) == 0:
        return 0.0
    mu = float(np.mean(portfolio_returns))
    sigma = float(np.std(portfolio_returns, ddof=1))
    # z quantile for (1 - alpha)
    z = _inverse_normal_cdf(1 - alpha)
    var = -(mu + z * sigma)
    return float(var if var > 0 else 0.0)


def historical_var(portfolio_returns: np.ndarray, alpha: float = 0.01) -> float:
    """
    Historical (empirical) VaR using bootstrap/percentile on historical returns.

    Args:
        portfolio_returns: 1-D numpy array of historical daily returns.
        alpha: tail probability (0.01 -> 1% worst returns).

    Returns:
        Positive VaR number (as fraction).
    """
    if portfolio_returns is None or len(portfolio_returns) == 0:
        return 0.0
    percentile = 100.0 * alpha
    # worst alpha-percentile (negative sign so VaR is positive)
    worst = np.percentile(portfolio_returns, percentile)
    return float(max(0.0, -worst))


def compute_portfolio_returns_from_positions(
    price_history: pd.DataFrame, positions: Dict[str, float]
) -> np.ndarray:
    """
    Given a price history dataframe and a dictionary of positions (ticker -> dollar exposure),
    compute a time series of portfolio returns (simple daily returns of portfolio value).

    Args:
        price_history: DataFrame with columns ['date', 'ticker', 'adj_close']. Must contain multiple tickers and dates.
        positions: dict mapping ticker -> dollar exposure (can be positive/negative).

    Returns:
        1-D numpy array of portfolio daily returns (aligned by date).
    """
    # Pivot price history to matrix: index=date, columns=ticker
    df = price_history.copy()
    df = df.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    # Ensure tickers in positions are present
    tickers = [t for t in positions.keys() if t in df.columns]
    if len(tickers) == 0:
        return np.array([])
    # Compute daily returns for each ticker
    price_matrix = df[tickers]
    returns = price_matrix.pct_change().dropna(how="all")
    # Convert dollar exposures to weights per day using notional (assume exposures fixed)
    notional = np.array([positions[t] for t in tickers], dtype=float)
    # Compute portfolio return series: daily_ret = (returns_matrix * notional).sum(axis=1) / total_notional
    total_notional = np.sum(np.abs(notional)) if np.sum(np.abs(notional)) > 0 else np.sum(notional)
    # If total_notional is zero, return empty
    if total_notional == 0:
        # fallback: compute returns as simple weighted by exposures sum
        port_rets = (returns.values * notional).sum(axis=1)
    else:
        port_rets = (returns.values * notional).sum(axis=1) / total_notional
    return np.asarray(port_rets, dtype=float)


def stop_loss_price(entry_price: float, stop_loss_pct: float, side: str = "LONG") -> float:
    """
    Compute the stop price given entry price and stop percentage.

    Args:
        entry_price: price at entry
        stop_loss_pct: stop threshold expressed as decimal (e.g., 0.03 for 3%)
        side: "LONG" or "SHORT"

    Returns:
        price at which a stop-loss should trigger
    """
    if side.upper() == "LONG":
        return float(entry_price * (1.0 - abs(stop_loss_pct)))
    else:
        # For a short, a stop (to cut loss) is above entry
        return float(entry_price * (1.0 + abs(stop_loss_pct)))


def emergency_drawdown_trigger(current_nav: float, peak_nav: float, trigger_drawdown: float) -> bool:
    """
    Check whether the current drawdown exceeds the emergency trigger.

    Args:
        current_nav: current portfolio net asset value
        peak_nav: previous peak NAV to measure drawdown from
        trigger_drawdown: threshold as decimal, e.g., 0.10 for 10% drawdown

    Returns:
        True if emergency trigger breached
    """
    if peak_nav <= 0:
        return False
    drawdown = (peak_nav - current_nav) / peak_nav
    return drawdown >= trigger_drawdown


def volatility_targeted_notional(
    base_notional: float, target_annual_vol: float, recent_returns: np.ndarray, max_scale: float = 2.0, min_scale: float = 0.3
) -> Dict[str, Any]:
    """
    Compute a volatility-targeted notional and return diagnostics.

    Args:
        base_notional: dollar notional suggested by strategy before vol targeting
        target_annual_vol: target vol (decimal)
        recent_returns: series of recent daily returns for the portfolio or instrument
        max_scale/min_scale: clamps for scale factor

    Returns:
        dict containing:
            - 'scaled_notional': float
            - 'scale_factor': float
            - 'recent_annual_vol': float
    """
    scale, recent_vol = compute_scale_factor(target_annual_vol, recent_returns, max_scale=max_scale, min_scale=min_scale)
    scaled_notional = float(base_notional * scale)
    return {"scaled_notional": scaled_notional, "scale_factor": scale, "recent_annual_vol": recent_vol}
