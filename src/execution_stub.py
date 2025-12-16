"""
src/execution_stub.py

Sandbox execution stub used by Hedge Engine.

This module provides a deterministic, auditable sandbox execution layer that simulates:
- market fills for MARKET and LIMIT orders,
- simple TWAP/TWAP-like algorithmic execution with participation caps,
- smart-order-routing by percent-of-ADV participation policy,
- slippage modeling and partial fills when size exceeds liquidity.

The stub is intentionally conservative and deterministic by default (you can pass a seed).
It is for testing/backtesting and operator training only — it does not connect to real brokers.
"""

from typing import Dict, Any, List, Optional, Tuple
import math
import random
import time


def _mock_fill_price(market_price: float, side: str, slippage_bps: float = 2.0, rng: Optional[random.Random] = None) -> float:
    """
    Return a simulated fill price given a market price and slippage in basis points.

    Args:
        market_price: reference market price (float)
        side: 'BUY' or 'SELL'
        slippage_bps: expected slippage in basis points (positive means worse for the taker)
        rng: optional Random instance for deterministic jitter

    Returns:
        fill_price: float
    """
    if rng is None:
        rng = random.Random(0)
    sign = 1 if side.upper() == "BUY" else -1
    # small random jitter around slippage to simulate partial market variation
    jitter = rng.uniform(-0.25, 0.25)  # +/- 25% of slippage
    slippage = slippage_bps * (1.0 + jitter) / 10000.0
    return market_price * (1.0 + sign * slippage)


def _slice_capacity_from_adv(adv_usd: float, percent_of_adv: float, slice_minutes: float, minutes_per_day: float = 390.0, price: float = 100.0) -> int:
    """
    Compute maximum number of shares (or contracts) allowed for a slice given ADV (in USD)
    and participation rate.

    Args:
        adv_usd: average daily volume in USD
        percent_of_adv: desired participation rate (e.g., 0.05 for 5%)
        slice_minutes: duration of the slice in minutes
        minutes_per_day: trading minutes per day (default 390)
        price: price per share for conversion to shares

    Returns:
        integer max shares allowed for that slice
    """
    if adv_usd <= 0 or price <= 0:
        return 0
    adv_per_minute = adv_usd / minutes_per_day
    slice_adv_usd = adv_per_minute * slice_minutes
    allowed_usd = slice_adv_usd * percent_of_adv
    allowed_shares = int(max(0, math.floor(allowed_usd / price)))
    return allowed_shares


def _simulate_twap_fill(order: Dict[str, Any],
                        market_price: float,
                        adv_usd: float,
                        percent_of_adv: float,
                        duration_minutes: int,
                        slices: int,
                        slippage_bps: float,
                        rng: Optional[random.Random]) -> Tuple[List[Dict[str, Any]], int]:
    """
    Simulate TWAP execution broken into `slices` over `duration_minutes`.
    Returns a tuple of (list_of_slice_fill_records, total_filled_qty).
    """
    qty = int(order.get("qty", 0))
    if qty <= 0 or slices <= 0:
        return [], 0

    slice_minutes = float(duration_minutes) / float(slices)
    remaining = qty
    fills = []
    for i in range(slices):
        # compute capacity for this slice from ADV and participation rate
        slice_capacity = _slice_capacity_from_adv(adv_usd=adv_usd,
                                                  percent_of_adv=percent_of_adv,
                                                  slice_minutes=slice_minutes,
                                                  price=market_price)
        # intended slice target (evenly split)
        intended = int(math.ceil(qty / float(slices)))
        allowed = min(intended, slice_capacity) if slice_capacity > 0 else intended
        # avoid zero allowed due to low ADV — allow at least 1 share if remaining small
        if allowed <= 0 and remaining > 0:
            allowed = min(remaining, 1)

        fill_qty = min(allowed, remaining)
        if fill_qty <= 0:
            fills.append({
                "slice": i + 1,
                "requested": intended,
                "filled": 0,
                "price": None,
                "status": "not_filled",
            })
            continue

        price = _mock_fill_price(market_price, order.get("side", "BUY"), slippage_bps=slippage_bps, rng=rng)
        fills.append({
            "slice": i + 1,
            "requested": intended,
            "filled": int(fill_qty),
            "price": float(price),
            "status": "filled"
        })
        remaining -= int(fill_qty)
        # tiny sleep to simulate time passing in sandbox (very short)
        time.sleep(0.01)
        if remaining <= 0:
            break

    total_filled = qty - remaining
    return fills, total_filled


def _execute_order_limit(order: Dict[str, Any],
                         market_price: float,
                         max_slippage_bps: float,
                         rng: Optional[random.Random]) -> Dict[str, Any]:
    """
    Simulate a LIMIT order execution: fill only if limit price is met.
    For BUY limit: fill if limit >= market_price (i.e., limit is at/above market).
    For SELL limit: fill if limit <= market_price.
    We'll simulate immediate fill if limit is aggressive; otherwise simulate no fill.

    Returns a dict describing the result for the order.
    """
    limit = order.get("limit", None)
    side = order.get("side", "BUY").upper()
    qty = int(order.get("qty", 0))
    result = {"requested": qty, "filled": 0, "avg_fill_price": None, "fills": [], "status": "not_filled"}

    if limit is None or qty <= 0:
        result["status"] = "invalid_order"
        return result

    # Check whether the limit is immediately marketable
    is_marketable = False
    if side == "BUY":
        is_marketable = (limit >= market_price)
    else:
        is_marketable = (limit <= market_price)

    if not is_marketable:
        # No immediate fill in this simple stub
        result["status"] = "no_fill"
        return result

    # If marketable, simulate full fill at favorable price (limit or better) with slippage
    # We simulate a slight improvement/worsening depending on side and random jitter
    fill_price = _mock_fill_price(limit, side, slippage_bps=max_slippage_bps, rng=rng)
    result["filled"] = qty
    result["avg_fill_price"] = float(fill_price)
    result["fills"].append({"qty": qty, "price": float(fill_price), "status": "filled"})
    result["status"] = "filled"
    return result


def _execute_order_market(order: Dict[str, Any],
                          market_price: float,
                          max_slippage_bps: float,
                          rng: Optional[random.Random]) -> Dict[str, Any]:
    """
    Simulate a MARKET order: fill immediately at market_price with slippage.
    """
    qty = int(order.get("qty", 0))
    side = order.get("side", "BUY")
    if qty <= 0:
        return {"requested": 0, "filled": 0, "avg_fill_price": None, "fills": [], "status": "invalid_order"}

    price = _mock_fill_price(market_price, side, slippage_bps=max_slippage_bps, rng=rng)
    return {"requested": qty, "filled": qty, "avg_fill_price": float(price), "fills": [{"qty": qty, "price": float(price), "status": "filled"}], "status": "filled"}


def _parse_sor_policy(sor_policy: Any) -> Dict[str, Any]:
    """
    Normalize the sor_policy into a dict:
    Expected forms:
       - "percent_of_adv=0.05"
       - {"mode":"percent_of_adv","percent":0.05}
    Returns:
       dict with keys: mode, percent
    """
    default = {"mode": "percent_of_adv", "percent": 0.05}
    if not sor_policy:
        return default
    if isinstance(sor_policy, str):
        try:
            if sor_policy.startswith("percent_of_adv="):
                p = float(sor_policy.split("=", 1)[1])
                return {"mode": "percent_of_adv", "percent": p}
        except Exception:
            return default
    if isinstance(sor_policy, dict):
        mode = sor_policy.get("mode", "percent_of_adv")
        percent = float(sor_policy.get("percent", sor_policy.get("p", 0.05)))
        return {"mode": mode, "percent": percent}
    return default


def execute_order(execution_plan: Dict[str, Any],
                  mode: str = "sandbox",
                  market_snapshot: Optional[Dict[str, Dict[str, Any]]] = None,
                  seed: Optional[int] = 0) -> Dict[str, Any]:
    """
    Execute an execution_plan in either 'sandbox' or 'live' mode.

    execution_plan example:
    {
      'orders': [
         {'ticker':'SPY','side':'BUY','qty':100,'type':'LIMIT','limit':430.0},
         {'ticker':'SSO','side':'BUY','qty':500,'type':'ALG','algo':'TWAP','duration_minutes':30,'slices':6}
       ],
      'sor_policy': 'percent_of_adv=0.05',
      'max_slippage_bps': 5
    }

    Args:
        execution_plan: plan dict
        mode: 'sandbox' (default) or 'live' (NotImplemented)
        market_snapshot: optional dict mapping ticker -> {'price':float,'adv':float}
        seed: RNG seed for deterministic simulation

    Returns:
        dict with keys: status, fills (per order), metrics
    """
    if mode != "sandbox":
        raise NotImplementedError("Live broker integration is not implemented in execution_stub.")

    rng = random.Random(seed if seed is not None else 0)
    sor = _parse_sor_policy(execution_plan.get("sor_policy", None))
    max_slippage_bps = float(execution_plan.get("max_slippage_bps", 5.0))
    fills_out = []
    overall_metrics = {"total_requested": 0, "total_filled": 0, "notional_filled_usd": 0.0}

    orders = execution_plan.get("orders", []) or []
    for order in orders:
        ticker = order.get("ticker")
        side = order.get("side", "BUY")
        ord_type = order.get("type", "MARKET").upper()
        qty = int(order.get("qty", 0))
        market_info = (market_snapshot.get(ticker, {}) if market_snapshot else {})
        market_price = float(market_info.get("price", order.get("limit", 100.0)))
        adv_usd = float(market_info.get("adv", 0.0))

        order_result = {
            "ticker": ticker,
            "requested_qty": qty,
            "filled_qty": 0,
            "avg_fill_price": None,
            "status": "not_executed",
            "fills": []
        }

        overall_metrics["total_requested"] += qty

        # If alg/TWAP specified
        if ord_type == "ALG" or order.get("algo", "").upper() == "TWAP":
            duration = int(order.get("duration_minutes", 30))
            slices = int(order.get("slices", 6))
            percent = float(order.get("percent_of_adv", sor.get("percent", 0.05)))
            slice_fills, total_filled = _simulate_twap_fill(order=order,
                                                            market_price=market_price,
                                                            adv_usd=adv_usd,
                                                            percent_of_adv=percent,
                                                            duration_minutes=duration,
                                                            slices=slices,
                                                            slippage_bps=max_slippage_bps,
                                                            rng=rng)
            order_result["fills"] = slice_fills
            order_result["filled_qty"] = int(total_filled)
            if total_filled >= qty:
                order_result["status"] = "filled"
            elif total_filled > 0:
                order_result["status"] = "partial"
            else:
                order_result["status"] = "no_fill"
            # compute avg price if any fills
            if total_filled > 0:
                total_val = sum(f.get("filled", 0) * f.get("price", market_price) for f in slice_fills if f.get("filled", 0) > 0)
                order_result["avg_fill_price"] = float(total_val / total_filled)
        else:
            # MARKET or LIMIT
            if ord_type == "MARKET":
                res = _execute_order_market(order, market_price, max_slippage_bps, rng)
            elif ord_type == "LIMIT":
                res = _execute_order_limit(order, market_price, max_slippage_bps, rng)
            else:
                # unknown type: treat as MARKET for sandbox simplicity
                res = _execute_order_market(order, market_price, max_slippage_bps, rng)

            order_result["fills"] = res.get("fills", [])
            order_result["filled_qty"] = int(res.get("filled", 0))
            order_result["avg_fill_price"] = res.get("avg_fill_price")
            order_result["status"] = res.get("status", "unknown")

        overall_metrics["total_filled"] += order_result["filled_qty"]
        if order_result["avg_fill_price"] is not None:
            overall_metrics["notional_filled_usd"] += order_result["filled_qty"] * float(order_result["avg_fill_price"])

        fills_out.append(order_result)

    return {"status": "ok", "fills": fills_out, "metrics": overall_metrics}


# Simple demo CLI
if __name__ == "__main__":
    sample_plan = {
        "orders": [
            {"ticker": "SPY", "side": "BUY", "qty": 100, "type": "MARKET"},
            {"ticker": "SSO", "side": "BUY", "qty": 2000, "type": "ALG", "algo": "TWAP", "duration_minutes": 30, "slices": 6}
        ],
        "sor_policy": "percent_of_adv=0.05",
        "max_slippage_bps": 3
    }
    # sample market snapshot
    market_snapshot = {
        "SPY": {"price": 430.12, "adv": 30_000_000.0},
        "SSO": {"price": 45.0, "adv": 8_000_000.0}
    }
    res = execute_order(sample_plan, mode="sandbox", market_snapshot=market_snapshot, seed=1)
    import json
    print(json.dumps(res, indent=2))
