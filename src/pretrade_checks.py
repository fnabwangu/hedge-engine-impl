"""
src/pretrade_checks.py

Simple, deterministic pre-trade checks used by the Decision Engine.

Functions:
- pass_liquidity_filters: basic liquidity and spread gate.
- instrument_allowed: check that an instrument is in the approved universe.
- compute_notional_usd: helper to compute notional from qty and price.
- pass_instrument_viability: higher-level gate combining liquidity, horizon, and whitelist checks.
"""

from typing import Dict, Iterable, Optional


def pass_liquidity_filters(
    ticker_metrics: Dict,
    adv_threshold_usd: float = 1_000_000,
    max_spread_bps: float = 5.0,
    min_ask_size: Optional[float] = None,
) -> bool:
    """
    Basic liquidity and spread filters.

    Args:
        ticker_metrics: dict that should contain keys like:
            - 'adv' (average daily volume in USD)
            - 'spread_bps' (bid-ask spread in basis points, e.g., 2.5)
            - optionally 'ask_size' (size at ask)
        adv_threshold_usd: minimum acceptable ADV in USD
        max_spread_bps: maximum acceptable bid/ask spread in bps
        min_ask_size: optional minimal displayed ask size (in shares or notional depending on metric)

    Returns:
        True if the instrument passes liquidity gates, False otherwise.
    """
    adv = float(ticker_metrics.get("adv", 0.0))
    spread = float(ticker_metrics.get("spread_bps", 9999.0))

    if adv < adv_threshold_usd:
        return False
    if spread > max_spread_bps:
        return False
    if min_ask_size is not None:
        ask_size = ticker_metrics.get("ask_size")
        if ask_size is None:
            return False
        try:
            if float(ask_size) < float(min_ask_size):
                return False
        except Exception:
            return False
    return True


def instrument_allowed(instrument: Dict, allowed_universe: Iterable[str]) -> bool:
    """
    Check that the instrument ticker exists in the allowed universe.

    Args:
        instrument: dict with at least 'ticker' key.
        allowed_universe: iterable of allowed ticker strings.

    Returns:
        True if allowed, False otherwise.
    """
    ticker = instrument.get("ticker")
    if not ticker:
        return False
    return ticker in set(allowed_universe)


def compute_notional_usd(qty: float, price: float) -> float:
    """
    Compute notional USD for a given quantity and price.

    Args:
        qty: number of shares/contracts
        price: price per unit in USD

    Returns:
        Notional in USD (float)
    """
    try:
        return float(qty) * float(price)
    except Exception:
        return 0.0


def pass_instrument_viability(
    instrument: Dict,
    ticker_metrics: Dict,
    allowed_universe: Iterable[str],
    adv_threshold_usd: float = 1_000_000,
    max_spread_bps: float = 5.0,
    min_ask_size: Optional[float] = None,
    max_notional_usd: Optional[float] = None,
    price: Optional[float] = None,
) -> Dict[str, object]:
    """
    Combined viability check returning a structured result.

    Args:
        instrument: {'ticker':..., 'type':..., 'leverage': ...}
        ticker_metrics: liquidity metrics for that ticker
        allowed_universe: allowed ticker set
        adv_threshold_usd, max_spread_bps, min_ask_size: liquidity params
        max_notional_usd: if provided, enforce cap on single trade notional
        price: optional price to compute notional (if qty present)

    Returns:
        dict with keys:
          - 'allowed' (bool),
          - 'reasons' (list of strings explaining failures),
          - 'notional_usd' (float, 0 if not computable)
    """
    reasons = []
    allowed = True

    if not instrument_allowed(instrument, allowed_universe):
        allowed = False
        reasons.append("instrument not in allowed universe")

    if not pass_liquidity_filters(ticker_metrics, adv_threshold_usd, max_spread_bps, min_ask_size):
        allowed = False
        reasons.append("failed liquidity/spread filters")

    qty = instrument.get("qty", None)
    notional = 0.0
    if qty is not None and price is not None:
        notional = compute_notional_usd(qty, price)
        if max_notional_usd is not None and notional > max_notional_usd:
            allowed = False
            reasons.append("exceeds max notional limit")

    return {"allowed": allowed, "reasons": reasons, "notional_usd": float(notional)}
