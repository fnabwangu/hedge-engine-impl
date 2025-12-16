"""
src/ev_calc.py

Expected Value (EV) calculation and viability gate for Hedge Engine.

Provides:
- compute_ev: compute gross EV, adjust for LETF decay, trading costs and slippage,
  and return a small dict of quantitative checks including viability boolean.
- compute_t_max: heuristic maximum safe holding period for LETFs given leverage
  and estimated annual volatility.

This module intentionally keeps deterministic math simple and auditable.
"""

from typing import Dict, Any, Optional


def compute_ev(
    signal: Dict[str, Any],
    decay_stats: Optional[Dict[str, Any]],
    trading_costs: float = 0.0,
    slippage: float = 0.0,
    safety_margin: float = 0.01,
) -> Dict[str, Any]:
    """
    Compute expected value for a candidate trade and decide viability.

    Args:
        signal: dict containing keys:
            - p_success (float 0..1)
            - expected_delta: { 'fav': float, 'neutral': float, 'unfav': float }
            - horizon_days: int (optional)
            - suggested_instrument: dict with at least 'type' and optional 'leverage'
            - p_confidence: optional float
        decay_stats: output from simulate_lef_decay (or None). Expected to have 'mean'.
        trading_costs: estimated round-trip trading costs (as fraction, e.g. 0.0005)
        slippage: estimated slippage fraction (e.g. 0.0003)
        safety_margin: minimum acceptable net EV (as fraction) to mark viability True.

    Returns:
        A dict with keys:
            - ev_gross: float
            - letf_decay: float (estimated drag to subtract)
            - ev_net: float
            - viability_pass: bool
            - notes: optional string
    """
    # Extract probabilities and scenario deltas
    p = float(signal.get("p_success", 0.0))
    expected = signal.get("expected_delta", {}) or {}
    fav = float(expected.get("fav", 0.0))
    neutral = float(expected.get("neutral", 0.0))
    unfav = float(expected.get("unfav", 0.0))

    # Basic EV gross calculation:
    # If the model provided only fav/unfav and p_success: EV = p*fav + (1-p)*unfav
    # If neutral is present but no explicit probabilities for it, treat neutral as 0 outcome
    # and use the fav/unfav formulation for simplicity and auditability.
    ev_gross = p * fav + (1.0 - p) * unfav

    # LETF decay adjustment: if decay_stats present, use negative mean as drag
    letf_decay = 0.0
    try:
        if decay_stats is not None and isinstance(decay_stats, dict):
            mean_decay = float(decay_stats.get("mean", 0.0))
            # If mean is negative, record positive drag value
            letf_decay = max(0.0, -mean_decay)
    except Exception:
        letf_decay = 0.0

    # Net EV subtracting decay and costs
    ev_net = ev_gross - letf_decay - float(trading_costs) - float(slippage)

    # Viability: pass if ev_net exceeds safety_margin and p_confidence not extremely low
    p_conf = float(signal.get("p_confidence", 1.0))
    # conservative rule: require reasonable confidence; low confidence forces human review even if EV positive
    confidence_gate = p_conf >= 0.7
    viability_pass = (ev_net > safety_margin) and confidence_gate

    notes = ""
    if not confidence_gate:
        notes = "Low model confidence; human review recommended."
    elif ev_net <= safety_margin:
        notes = "Net EV below safety margin."

    return {
        "ev_gross": float(ev_gross),
        "letf_decay": float(letf_decay),
        "ev_net": float(ev_net),
        "viability_pass": bool(viability_pass),
        "p_confidence": float(p_conf),
        "safety_margin": float(safety_margin),
        "notes": notes,
    }


def compute_t_max(leverage: float, est_vol_annual: float) -> int:
    """
    Heuristic maximum holding days (T_max) for LETF usage.

    Args:
        leverage: leverage factor (e.g., 3.0 or 2.0)
        est_vol_annual: estimated annual volatility of the underlying (decimal, e.g., 0.20)

    Returns:
        An integer number of trading days that is a conservative recommended upper bound.
    """
    if est_vol_annual <= 0:
        # pessimistic fallback
        est_vol_annual = 0.20

    # Baseline heuristics:
    # - For 3x: baseline safe horizon ~5 trading days at 20% vol
    # - For 2x: baseline safe horizon ~10 trading days at 20% vol
    baseline_vol = 0.20
    if abs(leverage) >= 3.0:
        days = int(max(1, round(5 * (baseline_vol / est_vol_annual))))
    elif abs(leverage) >= 2.0:
        days = int(max(1, round(10 * (baseline_vol / est_vol_annual))))
    else:
        days = int(max(1, round(30 * (baseline_vol / est_vol_annual))))

    # Clamp to reasonable bounds
    days = max(1, min(days, 90))
    return int(days)


# Simple CLI helper for quick local checks (not required)
if __name__ == "__main__":
    import argparse
    import numpy as np

    parser = argparse.ArgumentParser(description="Compute EV example")
    parser.add_argument("--p_success", type=float, default=0.7)
    parser.add_argument("--p_confidence", type=float, default=0.8)
    parser.add_argument("--fav", type=float, default=0.08)
    parser.add_argument("--unfav", type=float, default=-0.05)
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argu_
