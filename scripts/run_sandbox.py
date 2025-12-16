#!/usr/bin/env python3
"""
scripts/run_sandbox.py

Orchestration script to run Hedge Engine sandbox workflows.

Provides simple CLI to:
- prepare sandbox data (calls data/generate_sandbox_data.py)
- run a demo Decision Record (calls src.cli.run_demo)
- run the sandbox execution on the demo decision (calls src.cli.run_sandbox_signal_example)
- run the full flow: prepare data -> demo -> sandbox execution

Intended to be run from the repository root. The script will cd to the repo root
automatically when executed from the scripts/ directory.
"""

import argparse
import os
import subprocess
import sys
import traceback

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_GENERATOR = os.path.join(REPO_ROOT, "data", "generate_sandbox_data.py")
DECISION_PATH = os.path.join(REPO_ROOT, "data", "decision_demo.json")


def ensure_cwd():
    """Ensure current working directory is the repository root."""
    os.chdir(REPO_ROOT)


def run_data_generator(parquet_path: str = None) -> None:
    """
    Run the data generator script to create sandbox datasets.
    If parquet_path is provided, the generator will still write to ./data by default.
    """
    ensure_cwd()
    if not os.path.isfile(DATA_GENERATOR):
        raise FileNotFoundError(f"Data generator not found at {DATA_GENERATOR}")
    cmd = [sys.executable, DATA_GENERATOR]
    if parquet_path:
        # The generator doesn't accept a parquet path in the skeleton; call plain.
        pass
    print(f"[run_sandbox] Running data generator: {' '.join(cmd)}")
    subprocess.check_call(cmd)
    print("[run_sandbox] Sandbox data generation complete.")


def run_demo(parquet_path: str = None, ticker: str = "SPY", decision_out: str = DECISION_PATH):
    """
    Run the demo that creates a Decision Record (synthetic signal -> EV -> Decision Record)
    """
    ensure_cwd()
    # Add repo root to sys.path so `from src.cli import run_demo` works regardless of invocation dir
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    try:
        from src.cli import run_demo as demo_func
    except Exception:
        # If import fails, provide helpful traceback
        traceback.print_exc()
        raise

    print(f"[run_sandbox] Running demo (parquet={parquet_path}, ticker={ticker}) ...")
    # The run_demo implementation allows specifying parquet & ticker
    demo_func(parquet_path if parquet_path else None, ticker, out_path=decision_out)
    print(f"[run_sandbox] Demo written to: {decision_out}")


def run_execution(decision_path: str = DECISION_PATH):
    """
    Run the sandbox execution using the Decision Record at decision_path.
    This loads the decision, validates audit hash, builds an execution plan and
    sends it to the execution stub in sandbox mode.
    """
    ensure_cwd()
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    try:
        from src.cli import run_sandbox_signal_example
    except Exception:
        traceback.print_exc()
        raise

    print(f"[run_sandbox] Executing sandbox run for decision: {decision_path}")
    res = run_sandbox_signal_example(decision_path)
    print("[run_sandbox] Execution complete.")
    return res


def run_full(parquet_path: str = None, ticker: str = "SPY", decision_out: str = DECISION_PATH):
    """
    Full pipeline: generate data -> run demo -> run execution
    """
    print("[run_sandbox] Starting full sandbox flow...")
    run_data_generator(parquet_path)
    run_demo(parquet_path=parquet_path, ticker=ticker, decision_out=decision_out)
    run_execution(decision_out)
    print("[run_sandbox] Full sandbox flow finished.")


def parse_args():
    p = argparse.ArgumentParser(description="Hedge Engine sandbox runner")
    p.add_argument("action", choices=["prepare-data", "demo", "sandbox", "full"], help="Action to run")
    p.add_argument("--parquet", help="Optional path to parquet file for demo (default uses generator output)")
    p.add_argument("--ticker", default="SPY", help="Ticker to use for demo")
    p.add_argument("--decision", default=DECISION_PATH, help="Path to write/read Decision Record")
    return p.parse_args()


def main():
    args = parse_args()
    try:
        if args.action == "prepare-data":
            run_data_generator(parquet_path=args.parquet)
        elif args.action == "demo":
            # Ensure sandbox data exists; warn if it does not
            data_parquet = args.parquet if args.parquet else os.path.join(REPO_ROOT, "data", "sandbox_etf_prices.parquet")
            if not os.path.exists(data_parquet):
                print(f"[run_sandbox] Warning: data file {data_parquet} not present — running data generator.")
                run_data_generator()
            run_demo(parquet_path=args.parquet, ticker=args.ticker, decision_out=args.decision)
        elif args.action == "sandbox":
            if not os.path.exists(args.decision):
                print(f"[run_sandbox] Decision record {args.decision} not found. Run 'demo' first.")
                sys.exit(1)
            run_execution(decision_path=args.decision)
        elif args.action == "full":
            run_full(parquet_path=args.parquet, ticker=args.ticker, decision_out=args.decision)
        else:
            print(f"Unknown action: {args.action}")
            sys.exit(2)
    except subprocess.CalledProcessError as cpe:
        print(f"[run_sandbox] Command failed: {cpe}")
        sys.exit(cpe.returncode)
    except Exception as e:
        print(f"[run_sandbox] Error: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
