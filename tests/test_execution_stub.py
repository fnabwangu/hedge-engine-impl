# tests/test_execution_stub.py

import pytest
from src.execution_stub import execute_order


def test_market_order_fill():
    plan = {
        "orders": [
            {"ticker": "SPY", "side": "BUY", "qty": 100, "type": "MARKET"},
        ],
        "sor_policy": "percent_of_adv=0.05",
        "max_slippage_bps": 5,
    }
    market_snapshot = {"SPY": {"price": 100.0, "adv": 50_000_000.0}}
    result = execute_order(plan, mode="sandbox", market_snapshot=market_snapshot, seed=1)

    assert result["status"] == "ok"
    assert "fills" in result and len(result["fills"]) == 1
    order_res = result["fills"][0]
    assert order_res["requested_qty"] == 100
    assert order_res["filled_qty"] == 100
    assert order_res["avg_fill_price"] is not None
    assert result["metrics"]["total_requested"] == 100
    assert result["metrics"]["total_filled"] == 100


def test_limit_order_no_fill_and_fill():
    # Limit BUY below market -> no fill
    plan_no_fill = {
        "orders": [{"ticker": "SPY", "side": "BUY", "qty": 50, "type": "LIMIT", "limit": 99.0}],
        "sor_policy": "percent_of_adv=0.05",
        "max_slippage_bps": 5,
    }
    market_snapshot = {"SPY": {"price": 100.0, "adv": 10_000_000.0}}
    res_no = execute_order(plan_no_fill, mode="sandbox", market_snapshot=market_snapshot, seed=2)
    assert res_no["status"] == "ok"
    or0 = res_no["fills"][0]
    assert or0["requested_qty"] == 50
    assert or0["filled_qty"] == 0
    assert or0["status"] in ("no_fill", "not_filled")

    # Limit BUY at/above market -> filled
    plan_fill = {
        "orders": [{"ticker": "SPY", "side": "BUY", "qty": 50, "type": "LIMIT", "limit": 101.0}],
        "sor_policy": "percent_of_adv=0.05",
        "max_slippage_bps": 5,
    }
    res_yes = execute_order(plan_fill, mode="sandbox", market_snapshot=market_snapshot, seed=3)
    assert res_yes["status"] == "ok"
    or1 = res_yes["fills"][0]
    assert or1["requested_qty"] == 50
    assert or1["filled_qty"] == 50
    assert or1["avg_fill_price"] is not None
    assert or1["status"] == "filled"


def test_twap_partial_fill_due_to_low_adv():
    # Very large requested qty with small ADV should result in partial fills across slices
    plan = {
        "orders": [
            {
                "ticker": "SSO",
                "side": "BUY",
                "qty": 1_000_000,  # extremely large
                "type": "ALG",
                "algo": "TWAP",
                "duration_minutes": 20,
                "slices": 4,
            }
        ],
        "sor_policy": "percent_of_adv=0.05",
        "max_slippage_bps": 5,
    }
    # Low ADV so each slice capacity is tiny
    market_snapshot = {"SSO": {"price": 100.0, "adv": 1_000_000.0}}
    res = execute_order(plan, mode="sandbox", market_snapshot=market_snapshot, seed=4)

    assert res["status"] == "ok"
    assert len(res["fills"]) == 1
    or0 = res["fills"][0]
    # Should be partial (some fills but far less than requested)
    assert or0["requested_qty"] == 1_000_000
    assert 0 < or0["filled_qty"] < or0["requested_qty"]
    assert or0["status"] in ("partial", "filled", "no_fill")  # expect partial typically


def test_multiple_orders_metrics():
    plan = {
        "orders": [
            {"ticker": "SPY", "side": "BUY", "qty": 10, "type": "MARKET"},
            {"ticker": "SSO", "side": "BUY", "qty": 200, "type": "ALG", "algo": "TWAP", "duration_minutes": 30, "slices": 6},
        ],
        "sor_policy": "percent_of_adv=0.05",
        "max_slippage_bps": 5,
    }
    market_snapshot = {
        "SPY": {"price": 430.12, "adv": 30_000_000.0},
        "SSO": {"price": 45.0, "adv": 8_000_000.0},
    }
    res = execute_order(plan, mode="sandbox", market_snapshot=market_snapshot, seed=5)
    assert res["status"] == "ok"
    assert res["metrics"]["total_requested"] == 10 + 200
    assert res["metrics"]["total_filled"] <= res["metrics"]["total_requested"]
    # Ensure notional is computed when avg_fill_price present
    assert "notional_filled_usd" in res["metrics"]
    assert res["metrics"]["notional_filled_usd"] >= 0.0
