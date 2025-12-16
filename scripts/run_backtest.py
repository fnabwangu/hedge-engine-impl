#!/usr/bin/env python3
"""
scripts/run_backtest.py

Minimal backtest driver for Hedge Engine sandbox.

This script runs a lightweight event-driven backtest over the sandbox dataset.
For each backtest date it:
 - constructs a simple rule-based signal (demo only),
 - runs LETF decay simulation and EV gate,
 - if viable, builds an execution plan and calls the sandbox execution stub,
 - writes a Decision Record and execution result to data/decision_records/.

This is a demonstration harness — replace the signal-generation with
your LLM-driven flow for real experiments.
"""
import os
import json
from datetime import timedelta
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd

# Ensure repo src is importable when running from scripts/
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in __import__("sys").path:
    __import__("sys").path.insert(0, REPO_ROOT)

from src.decay_sim import simulate_lef_decay
from src.ev_calc import compute_ev
from src.audit import make_decision_record, save_decision_record
from src.execution_stub import execute_order
from src.cli import build_execution_plan_from_decision

DATA_PARQUET = os.path.join(REPO_ROOT, "data", "sandbox_etf_prices.parquet")
DECISION_DIR = os.path.join(REPO_ROOT, "data", "decision_records")
os.makedirs(DECISION_DIR, exist_ok=True)


def load_market_df(parquet_path: str = DATA_PARQUET) -> pd.DataFrame:
    df = pd.read_parquet(parquet_path)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def get_price_on_date(df: pd.DataFrame, ticker: str, date) -> Optional[float]:
    row = df[(df["ticker"] == ticker) & (df["date"] == date)]
    if row.empty:
        return None
    return float(row.iloc[0]["adj_close"])


def get_adv_on_date(df: pd.DataFrame, ticker: str, date) -> float:
    # crude ADV: mean volume over prior 30 days * price at date
    sub = df[(df["ticker"] == ticker) & (df["date"] < date)].tail(30)
    if sub.empty:
        return 0.0
    mean_vol = float(sub["volume"].mean())
    price = get_price_on_date(df, ticker, date) or (sub["adj_close"].iloc[-1] if len(sub) else 1.0)
    return mean_vol * price


def simple_rule_signal(df: pd.DataFrame, date, ticker: str = "SPY") -> Optional[Dict[str, Any]]:
    """
    Very simple, deterministic rule to generate LLM-like signals:
    - If 5-day return > +1% => bullish signal (BUY SSO, 2x).
    - If 5-day return < -1% => bearish signal (SELL SSO, 2x).
    - Else => no signal (return None).
    """
    price_today = get_price_on_date(df, ticker, date)
    if price_today is None:
        return None
    # find index of date
    idx = df[(df["ticker"] == ticker) & (df["date"] == date)].index
    if len(idx) == 0:
        return None
    idx = idx[0]
    # Get prior 5 trading days for that ticker
    prev_rows = df[(df["ticker"] == ticker) & (df.index < idx)].tail(6)
    if len(prev_rows) < 6:
        return None
    past_price = float(prev_rows.iloc[0]["adj_close"])
    r5 = price_today / past_price - 1.0
    if r5 > 0.01:
        # bullish
        return {
            "p_success": 0.70,
            "p_confidence": 0.80,
            "horizon_days": 5,
            "expected_delta": {"fav": 0.03, "neutral": 0.0, "unfav": -0.02},
            "suggested_instrument": {"type": "LETF", "ticker": "SSO", "leverage": 2},
            "rationale": f"5-day return {r5:.3%} > 1% -> bullish",
            "flags": {"requires_human_review": False},
        }
    elif r5 < -0.01:
        # bearish: we place a SELL of SSO (short)
        return {
            "p_success": 0.65,
            "p_confidence": 0.75,
            "horizon_days": 5,
            "expected_delta": {"fav": 0.02, "neutral": 0.0, "unfav": -0.03},
            "suggested_instrument": {"type": "LETF", "ticker": "SSO", "leverage": 2},
            "rationale": f"5-day return {r5:.3%} < -1% -> bearish",
            "flags": {"requires_human_review": True},
        }
    else:
        return None


def run_backtest(start_date=None, end_date=None, step_days: int = 5):
    df = load_market_df()
    # choose trading dates (unique dates where SPY traded)
    dates = sorted(df["date"].unique())
    # optionally trim start/end
    if start_date is not None:
        dates = [d for d in dates if d >= pd.Timestamp(start_date)]
    if end_date is not None:
        dates = [d for d in dates if d <= pd.Timestamp(end_date)]
    # sample every step_days-th date for signals (simple cadence)
    dates_to_run = dates[::step_days]
    summary = {"decisions": 0, "executed": 0, "skipped": 0}
    for date in dates_to_run:
        # generate signal
        signal = simple_rule_signal(df, date, ticker="SPY")
        if signal is None:
            summary["skipped"] += 1
            continue

        # prepare decay sim using underlying returns up to date (use SPY)
        hist = df[(df["ticker"] == "SPY") & (df["date"] < date)].sort_values("date")
        if hist.shape[0] < 30:
            summary["skipped"] += 1
            continue
        returns = hist["adj_close"].pct_change().dropna().to_numpy()
        decay_stats = simulate_lef_decay(returns, leverage=float(signal["suggested_instrument"].get("leverage", 2.0)), window=int(signal["horizon_days"]), trials=2000, seed=42)

        # EV gate
        ev = compute_ev(signal, decay_stats, trading_costs=0.0005, slippage=0.0005, safety_margin=0.005)

        # build decision record
        decision = {
            "timestamp_utc": pd.to_datetime(date).isoformat(),
            "model_version": "rule-demo-v0",
            "prompt_hash": "rule-demo",
            "llm_output": signal,
            "quant_checks": ev,
            "inputs": {"date": str(date), "ticker": "SPY"},
        }
        # increment decisions count
        summary["decisions"] += 1

        # prepare execution if viable
        exec_result = None
        if ev.get("viability_pass"):
            # create a market_snapshot for execution stub
            price = get_price_on_date(df, signal["suggested_instrument"]["ticker"], date)
            if price is None:
                # fallback to SPY price as proxy
                price = get_price_on_date(df, "SPY", date)
            adv = get_adv_on_date(df, signal["suggested_instrument"]["ticker"], date)
            market_snapshot = {
                signal["suggested_instrument"]["ticker"]: {"price": price or 100.0, "adv": adv or 0.0}
            }
            # build an execution plan using CLI helper
            plan = build_execution_plan_from_decision(decision, portfolio_nav=1_000_000.0, price_map={signal["suggested_instrument"]["ticker"]: price or 100.0})
            # set order side depending on rationale (if requires_human_review true, we still attempt but note)
            # For bearish signals we issue SELL, else BUY
            if "bearish" in signal.get("rationale", "").lower():
                for o in plan["orders"]:
                    o["side"] = "SELL"
            # call sandbox execution stub
            exec_result = execute_order(plan, mode="sandbox", market_snapshot=market_snapshot, seed=123)
            summary["executed"] += 1

            # attach execution plan/result to decision
            decision["execution_plan"] = plan
            decision["execution_result"] = exec_result
        else:
            # attach plan None and reason
            decision["execution_plan"] = None
            decision["execution_result"] = {"status": "not_executed", "reason": ev.get("notes", "not viable")}

        # finalize and save decision record
        rec = make_decision_record(decision)
        fname = os.path.join(DECISION_DIR, f"decision_{pd.to_datetime(date).strftime('%Y%m%d')}_{summary['decisions']}.json")
        save_decision_record(rec, fname)

    # print summary
    print("Backtest complete.")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Run a simple sandbox backtest")
    p.add_argument("--start", help="Start date YYYY-MM-DD", default=None)
    p.add_argument("--end", help="End date YYYY-MM-DD", default=None)
    p.add_argument("--step", help="Sampling step in days", type=int, default=5)
    args = p.parse_args()
    run_backtest(start_date=args.start, end_date=args.end, step_days=args.step)
