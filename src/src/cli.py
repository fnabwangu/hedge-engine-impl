"""
src/cli.py

Simple command-line helpers and demo runner for Hedge Engine.

Provides:
- run_demo(): create a synthetic LLM-style signal, run deterministic checks,
  build a Decision Record and save it to disk.
- run_sandbox_signal_example(): read the demo Decision Record, prepare an
  execution plan and call the sandbox execution stub.
- small helpers to build an execution plan and to read sandbox data.
"""

import json
import os
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

from src.decay_sim import simulate_lef_decay
from src.ev_calc import compute_ev, compute_t_max
from src.audit import make_decision_record, save_decision_record, load_decision_record, verify_audit_hash
from src.execution_stub import execute_order
from src.pretrade_checks import pass_instrument_viability
from src.risk_engine import compute_scale_factor

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DEFAULT_SANDBOX_PARQUET = os.path.join(DATA_DIR, "sandbox_etf_prices.parquet")
DECISION_DEMO_PATH = os.path.join(DATA_DIR, "decision_demo.json")


def load_returns_from_parquet(path: str, ticker: str = "SPY") -> np.ndarray:
    """Load adjusted-close returns for `ticker` from a parquet file."""
    df = pd.read_parquet(path)
    df = df.sort_values("date")
    tdf = df[df["ticker"] == ticker]
    if tdf.empty:
        raise ValueError(f"No data for ticker {ticker} in {path}")
    returns = tdf["adj_close"].pct_change().dropna().to_numpy(dtype=float)
    return returns


def build_execution_plan_from_decision(decision: Dict[str, Any],
                                      portfolio_nav: float = 1_000_000.0,
                                      price_map: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Build a simple execution plan from a Decision Record.

    - Sizes by a nominal allocation fraction of the portfolio (default 2%).
    - Uses TWAP if notional is large relative to ADV or if the instrument is LETF.
    """
    if price_map is None:
        price_map = {}

    llm_signal = decision.get("llm_output") or decision.get("llm_signal") or {}
    instr = llm_signal.get("suggested_instrument", {})
    ticker = instr.get("ticker", "SPY")
    leverage = instr.get("leverage", instr.get("lev", 1))
    # default allocation fraction (tunable)
    alloc_frac = 0.02  # 2% of NAV
    target_notional = float(portfolio_nav) * alloc_frac
    price = float(price_map.get(ticker, instr.get("price", 100.0)))
    qty = int(max(1, round(target_notional / price)))
    # construct order
    order = {
        "ticker": ticker,
        "side": "BUY",
        "qty": qty,
        "type": "ALG" if qty > 1000 or instr.get("type", "").upper() == "LETF" else "MARKET",
    }
    # if ALG add TWAP params
    if order["type"] == "ALG":
        order.update({"algo": "TWAP", "duration_minutes": 30, "slices": 6})
    return {
        "orders": [order],
        "sor_policy": "percent_of_adv=0.05",
        "max_slippage_bps": 5
    }


def run_demo(parquet_path: str = DEFAULT_SANDBOX_PARQUET,
             ticker: str = "SPY",
             out_path: str = DECISION_DEMO_PATH,
             seed: int = 123):
    """
    Create a synthetic LLM signal, run decay simulation and EV gate,
    assemble a Decision Record and write it to disk.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # load returns
    try:
        returns = load_returns_from_parquet(parquet_path, ticker=ticker)
    except Exception:
        # fall back to synthetic returns
        rng = np.random.default_rng(seed)
        returns = rng.normal(0, 0.01, 1000)

    # simulate decay for a default horizon
    horizon = 5
    leverage = 3.0
    decay_stats = simulate_lef_decay(returns, leverage=leverage, window=horizon, trials=2000, seed=seed)

    # build synthetic llm signal (as if produced by the prompt)
    signal = {
        "p_success": 0.7,
        "p_confidence": 0.82,
        "horizon_days": horizon,
        "expected_delta": {"fav": 0.08, "neutral": 0.0, "unfav": -0.05},
        "suggested_instrument": {"type": "LETF", "ticker": "SSO", "leverage": leverage},
        "rationale": "Synthetic demo: tactical LETF hedge for short horizon",
        "evidence": [
            {"source_id": "DEMO.1", "type": "synthetic", "filecite": "demo|L1-L2", "excerpt": "Synthetic demo evidence."}
        ],
        "flags": {"requires_human_review": False}
    }

    # compute EV
    ev_result = compute_ev(signal, decay_stats, trading_costs=0.0005, slippage=0.0005, safety_margin=0.01)

    decision = {
        "llm_output": signal,
        "quant_checks": ev_result,
        "prompt_hash": "demo_prompt_hash_0001",
        "model_version": "demo-model-v1",
        "inputs": {"market_snapshot": {"ticker": ticker}, "decay_stats": decay_stats}
    }

    rec = make_decision_record(decision)
    save_decision_record(rec, out_path)
    print(f"Decision demo written to: {out_path}")
    print(json.dumps(rec, indent=2))


def run_sandbox_signal_example(decision_path: str = DECISION_DEMO_PATH,
                               market_snapshot: Optional[Dict[str, Dict[str, Any]]] = None):
    """
    Load a saved Decision Record, prepare an execution plan, and call
    the sandbox execution stub. Prints results and returns the execution result.
    """
    if not os.path.exists(decision_path):
        print(f"No decision at {decision_path}. Run run_demo() first.")
        return None

    rec = load_decision_record(decision_path)
    audit_ok = verify_audit_hash(rec)
    if not audit_ok:
        print("Warning: audit hash verification failed for decision record.")

    llm = rec.get("llm_output") or rec.get("llm_signal") or {}
    instr = llm.get("suggested_instrument", {})
    ticker = instr.get("ticker", "SPY")

    # simple market_snapshot fallback
    if market_snapshot is None:
        market_snapshot = {
            ticker: {"price": 100.0, "adv": 5_000_000.0}
        }

    plan = build_execution_plan_from_decision(rec, portfolio_nav=1_000_000.0, price_map={ticker: market_snapshot[ticker]["price"]})
    print("Execution plan:", json.dumps(plan, indent=2))
    res = execute_order(plan, mode="sandbox", market_snapshot=market_snapshot, seed=42)
    print("Execution result:", json.dumps(res, indent=2))
    # Attach execution_plan to decision and re-save for audit
    rec["execution_plan"] = plan
    rec["execution_result"] = res
    # recompute audit hash for the updated record (we want to preserve audit of pre-execution state;
    # for a live system you'd append a new Decision Record or an execution record instead)
    rec["post_execution_audit_hash"] = make_decision_record(rec).get("audit_hash")
    save_decision_record(rec, decision_path)
    return res


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hedge Engine CLI demo")
    parser.add_argument("action", choices=["demo", "sandbox"], help="Action to run (demo|sandbox)")
    parser.add_argument("--parquet", default=DEFAULT_SANDBOX_PARQUET, help="Path to sandbox parquet")
    parser.add_argument("--ticker", default="SPY", help="Ticker for demo")
    args = parser.parse_args()

    if args.action == "demo":
        run_demo(parquet_path=args.parquet, ticker=args.ticker)
    elif args.action == "sandbox":
        run_sandbox_signal_example()
