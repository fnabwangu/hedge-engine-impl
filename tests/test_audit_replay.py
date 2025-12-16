# tests/test_audit_replay.py

import json
from pathlib import Path

from src.audit import (
    make_decision_record,
    save_decision_record,
    load_decision_record,
    verify_audit_hash,
    replay_decision,
)


def test_audit_record_and_replay(tmp_path: Path):
    # Build a minimal decision record
    decision = {
        "llm_output": {"p_success": 0.8, "p_confidence": 0.85},
        "quant_checks": {"ev_gross": 0.08, "letf_decay": 0.002, "ev_net": 0.05, "viability_pass": True},
        "prompt_hash": "test_prompt_hash",
        "model_version": "test-model-v1",
        "inputs": {"market_snapshot": {"SPY": {"price": 400.0}}},
    }

    rec = make_decision_record(decision)
    path = tmp_path / "decision_rec.json"
    save_decision_record(rec, str(path))

    # Load and verify saved record
    loaded = load_decision_record(str(path))
    assert loaded["decision_id"] == rec["decision_id"]
    assert "audit_hash" in loaded
    assert verify_audit_hash(loaded) is True

    # Replay without a validator (should return audit_ok True and validation_ok None)
    res = replay_decision(str(path))
    assert res["audit_ok"] is True
    assert res["validation_ok"] is None
    assert "decision" in res


def test_replay_with_deterministic_validator(tmp_path: Path):
    # Create decision record
    decision = {
        "llm_output": {"p_success": 0.75, "p_confidence": 0.9},
        "quant_checks": {"ev_gross": 0.10, "letf_decay": 0.003, "ev_net": 0.096, "viability_pass": True},
        "prompt_hash": "validator_prompt_hash",
        "model_version": "validator-model-v1",
    }

    rec = make_decision_record(decision)
    path = tmp_path / "decision_rec2.json"
    save_decision_record(rec, str(path))

    # Validator that returns matching values -> validation_ok True
    def matching_validator(decision_record):
        # Return the same quant_checks to simulate deterministic recompute
        return decision_record.get("quant_checks", {}).copy()

    res_ok = replay_decision(str(path), deterministic_validator=matching_validator)
    assert res_ok["audit_ok"] is True
    assert res_ok["validation_ok"] is True
    assert res_ok["mismatches"] == {}

    # Validator that returns a mismatched value -> validation_ok False
    def mismatching_validator(decision_record):
        d = decision_record.get("quant_checks", {}).copy()
        # Slightly alter ev_net to force mismatch
        d["ev_net"] = d.get("ev_net", 0.0) + 0.12345
        return d

    res_bad = replay_decision(str(path), deterministic_validator=mismatching_validator)
    assert res_bad["audit_ok"] is True
    assert res_bad["validation_ok"] is False
    assert "ev_net" in res_bad["mismatches"]
    assert res_bad["mismatches"]["ev_net"]["expected"] == rec["quant_checks"]["ev_net"]
