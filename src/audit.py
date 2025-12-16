"""
src/audit.py

Audit utilities for Hedge Engine.

This module provides small, auditable helpers to create Decision Records,
compute and verify an audit hash, save/load records, and perform a basic
replay/validation check. The intention is to make Decision Records
self-contained, reproducible, and tamper-evident.

Functions:
- make_decision_record(decision: dict) -> dict
- compute_audit_hash(decision: dict) -> str
- verify_audit_hash(decision: dict) -> bool
- sign_decision(decision: dict, signer: str) -> dict
- save_decision_record(decision: dict, path: str) -> None
- load_decision_record(path: str) -> dict
- replay_decision(path: str, deterministic_validator: Optional[callable]) -> dict

Notes:
- The audit_hash is a SHA-256 over a canonical JSON serialization of the
  Decision Record **without** the 'audit_hash' and 'signature' fields.
- The `deterministic_validator` (if provided to replay_decision) should be
  a callable that accepts the Decision Record and returns a dict with any
  recomputed numeric checks (e.g. EV calc) to compare against stored values.
"""

from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Callable


def _canonical_json_bytes(obj: Dict[str, Any]) -> bytes:
    """
    Produce a canonical JSON byte representation for hashing.
    Sort keys, remove whitespace variance, and ensure stable encoding.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_audit_hash(decision: Dict[str, Any]) -> str:
    """
    Compute a SHA-256 audit hash for a decision dict.

    The hash is computed over a canonical JSON serialization of the decision
    after removing any existing 'audit_hash' and 'signature' fields to avoid
    self-reference.

    Returns:
        hex digest string of SHA-256
    """
    # Make a shallow copy and remove audit/signature if present
    copy = dict(decision)
    copy.pop("audit_hash", None)
    copy.pop("signature", None)
    # We stringify in a canonical way
    data = _canonical_json_bytes(copy)
    h = hashlib.sha256(data).hexdigest()
    return h


def make_decision_record(decision: Dict[str, Any], ensure_ids: bool = True) -> Dict[str, Any]:
    """
    Prepare and return a Decision Record suitable for persistent audit storage.

    - Ensures 'decision_id' (UUID4) present.
    - Adds/normalizes 'timestamp_utc' if missing.
    - Computes and attaches 'audit_hash'.
    - Does NOT apply cryptographic signature (use sign_decision()).

    Args:
        decision: partial decision dict (llm_output, quant_checks, etc.)
        ensure_ids: whether to generate decision_id/timestamp if missing.

    Returns:
        decision dict augmented with decision_id, timestamp_utc, audit_hash.
    """
    rec = dict(decision)  # shallow copy to avoid mutating input
    if ensure_ids:
        if "decision_id" not in rec or not rec.get("decision_id"):
            rec["decision_id"] = uuid.uuid4().hex
        if "timestamp_utc" not in rec or not rec.get("timestamp_utc"):
            # ISO 8601 UTC
            rec["timestamp_utc"] = datetime.now(timezone.utc).isoformat()

    # Compute audit_hash and attach
    rec["audit_hash"] = compute_audit_hash(rec)
    return rec


def sign_decision(decision: Dict[str, Any], signer: str) -> Dict[str, Any]:
    """
    Attach a lightweight, auditable signature to the decision record.

    This is a convenience helper and **not** a cryptographically secure signature
    (no private keys used). It produces a deterministic signature string composed
    of signer name and a SHA-256 digest over (audit_hash + signer).

    For production-grade non-repudiation, replace this with a private-key
    cryptographic signature stored separately.

    Args:
        decision: decision record (must have 'audit_hash')
        signer: string identifier of signer (e.g., 'Alice <alice@example.com>')

    Returns:
        decision dict with 'signature' field added.
    """
    if "audit_hash" not in decision:
        raise ValueError("Decision must include 'audit_hash' before signing.")
    payload = (decision["audit_hash"] + "|" + signer).encode("utf-8")
    sig = hashlib.sha256(payload).hexdigest()
    signature = {"signed_by": signer, "signature_hash": sig, "signed_at": datetime.now(timezone.utc).isoformat()}
    rec = dict(decision)
    rec["signature"] = signature
    # Recompute audit_hash since we added signature field? Typically audit_hash covers the record
    # without signature. We keep behavior: audit_hash covers pre-signature state (so do not recompute).
    return rec


def save_decision_record(decision: Dict[str, Any], path: str) -> None:
    """
    Save the decision record to the given file path (JSON pretty-printed).

    Overwrites any existing file at path.
    """
    # Ensure audit_hash is present
    if "audit_hash" not in decision:
        decision = make_decision_record(decision)
    # Write pretty JSON with stable ordering for human readability
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(decision, fh, indent=2, sort_keys=True, ensure_ascii=False)


def load_decision_record(path: str) -> Dict[str, Any]:
    """
    Load a Decision Record from a JSON file.
    """
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def verify_audit_hash(decision: Dict[str, Any]) -> bool:
    """
    Verify that the audit_hash on the decision matches a recomputed hash.

    Returns True if the stored audit_hash equals the recomputed value.
    """
    stored = decision.get("audit_hash")
    if not stored:
        return False
    recomputed = compute_audit_hash(decision)
    return stored == recomputed


def replay_decision(path: str, deterministic_validator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Replay and validate a Decision Record.

    - Loads the record from `path`.
    - Verifies the audit_hash matches.
    - Optionally runs `deterministic_validator`, a callable that accepts the Decision Record
      and returns a dict of recomputed deterministic values (e.g., quant_checks). If provided,
      `replay_decision` will compare these recomputed values to the stored values and report mismatches.

    The `deterministic_validator` should not call external non-deterministic services; it should
    only run the deterministic code used in production (EV calc, decay sim with fixed seeds, etc.).

    Returns a dict with:
      - 'decision': the loaded record
      - 'audit_ok': bool
      - 'validation_ok': bool or None (None if no validator provided)
      - 'mismatches': dict of field->(expected, actual) for any differences
    """
    rec = load_decision_record(path)
    audit_ok = verify_audit_hash(rec)
    result = {"decision": rec, "audit_ok": audit_ok, "validation_ok": None, "mismatches": {}}

    if deterministic_validator is not None:
        try:
            recomputed = deterministic_validator(rec)
            mismatches = {}
            # Compare numeric keys in recomputed to stored values in rec['quant_checks'] if exists
            stored_checks = rec.get("quant_checks", {})
            for k, v in recomputed.items():
                if k in stored_checks:
                    # Compare floats with small tolerance when applicable
                    stored_val = stored_checks[k]
                    try:
                        fv = float(v)
                        fs = float(stored_val)
                        if not abs(fv - fs) <= max(1e-9, 1e-8 * max(1.0, abs(fs))):
                            mismatches[k] = {"expected": stored_val, "actual": v}
                    except Exception:
                        if stored_val != v:
                            mismatches[k] = {"expected": stored_val, "actual": v}
                else:
                    # Recomputation returned a field not present in stored checks - record it
                    mismatches[k] = {"expected": None, "actual": v}
            result["mismatches"] = mismatches
            result["validation_ok"] = len(mismatches) == 0
        except Exception as e:
            result["validation_ok"] = False
            result["mismatches"] = {"_validator_error": str(e)}
    return result
