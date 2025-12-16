# Kill Switch — Hedge Engine

## Purpose
This document defines the operator-facing kill-switch policy, procedures, and exact steps to **immediately** stop live trading activity and place the system into a safe, auditable "shadow" state. The kill switch is the highest-priority operational control for safety, risk and compliance.

**Key properties**
- Activation must be fast and deterministic.
- Reactivation requires **two-person custody** (two authorized approvers).
- Every action is recorded in the audit ledger with immutable evidence.

---

## Scope
Applies to the Execution Agent and any component that can submit live orders (sandbox excluded). The kill-switch must prevent any new live order from being submitted and should optionally attempt a safe unwind per operator policy.

---

## Activation conditions (examples)
One or more of:
- Model hallucination metric spike above threshold (configurable).
- Execution slippage exceeding configured limits.
- Unexpected, sustained P/L drawdown or emergency drawdown trigger (e.g., > 10% P2T).
- Broker or market connectivity failure causing unsafe conditions.
- Security incident or suspected compromise.
- Manual operator decision during an incident.

---

## Who may activate
- Any on-call Operator listed in the Operator Contacts with "Kill" privileges (see `ADDENDUM.md`).
- Activation may be automated by telemetry rules that have been explicitly authorized in policy.

---

## Immediate objectives on activation
1. Stop new live executions (auto & manual).  
2. Place Execution Agent into **shadow** or **disabled** mode so no outbound orders go to brokers.  
3. Preserve state for forensics: Decision Records, execution logs, model_version, prompt_hash, telemetry.  
4. Notify Compliance, Security, and custodians.  
5. Start incident triage and follow the incident response playbook.

---

## Activation methods (choose one or more per deployment)

### 1) Operator Console / Web UI (preferred)
- Click **KILL SWITCH / ENTER SHADOW MODE** button.
- Require operator to provide reason and username.
- Console posts an append-only audit entry and flips runtime flag.

### 2) Environment Toggle (CLI) — quick manual
From a secure operator host with appropriate permissions:

```bash
# Set kill switch (effective immediately)
# NOTE: adapt command to your environment management (systemctl, kubectl, etc.)
export HEDGE_KILL_SWITCH=1
# Or write to config store:
curl -X POST https://operator-console.example/api/kill-switch \
3) Cloud / Feature Flag

Flip a protected feature-flag in the feature-flagging system (2FA required).

Flag change triggers agents to switch to shadow mode.

4) Broker-side disable (last resort)

Block broker API keys or revoke execution credentials (requires coordination with broker and legal).

Checklist: Activation (operator steps)

Record: Before or immediately after activation, create an audit note with:

operator, role, timestamp (UTC), reason, evidence (links), model_version, prompt_hash.

Activate: Use one of the activation methods above.

Verify: Confirm Execution Agent reports mode=shadow and that live_submissions=0.

Snapshot: Export and upload to secure storage:

Decision Records since T-24h

Execution logs

Telemetry (hallucination metric, slippage, VaR)

Model version & prompt_hash

Notify: Immediately alert Compliance, Security, and custodians via pre-defined channels.

Contain: Stop any automated re-try or recovery flows that would submit orders.

Triage: Start incident triage per SECURITY.md / Addendum runbook.

Technical verification steps (post-activation)

Confirm via API: GET /operator/status returns "execution_mode": "shadow".

Confirm no order activity: search last-minute order logs, ensure zero outbound live order calls.

Confirm telemetry: hallucination and slippage metrics are flagged / elevated.

Example API check:

curl -s -H "Authorization: Bearer $OP_TOKEN" https://operator-console.example/api/status | jq .
# Expect: { "execution_mode": "shadow", "live_order_count": 0, "kill_switch": true }

Unwind / exit strategy

Unwind decisions must be explicit, approved and auditable. Options:

Do nothing: leave positions as-is (preferred when forced to pause).

Safe unwind: execute pre-approved unwind scripts to flatten positions with tight limits and human oversight.

Partial hedge: reduce exposure to min_exposure_floor (e.g., 30%) and await review.

Important: Do not run unwind automatically unless pre-authorized. Any unwind must be recorded as an execution action in the audit ledger.

Reactivation (Two-person custody)

To re-enable live trading:

Prepare: Incident root-cause analysis and mitigation steps documented. Post-mortem plan prepared.

Approval: Two distinct custodians (A and B) must each:

Review incident summary,

Confirm mitigations are implemented,

Record electronic approval (name, email, timestamp, short rationale).

Execute reactivation:

Operator A executes a reactivation request; Operator B confirms.

System records both signatures in audit ledger.

CI/QA shadow-run must pass pre-flight checks for a configurable period (e.g., 24–72 hours) before automated scaling.

Post-reactivation monitoring: Increase telemetry sampling and human review frequency for at least 72 hours.

Example reactivation API (conceptual):

curl -X POST https://operator-console.example/api/kill-switch/reactivate \
  -H "Authorization: Bearer $CUSTODIAN_A_TOKEN" \
  -d '{"operator":"a@example.com","approval":"yes","notes":"fix applied"}'

# Second custodian
curl -X POST https://operator-console.example/api/kill-switch/confirm \
  -H "Authorization: Bearer $CUSTODIAN_B_TOKEN" \
  -d '{"operator":"b@example.com","approval":"yes","notes":"validated"}'

Audit & logging requirements

Every activation, attempted activation, reactivation and test must create an immutable audit entry containing:

action: activate / deactivate / test / approve / reject

actor: operator identifier (email)

role: operator role (Engineering/Compliance/Security)

timestamp_utc

reason (free text)

evidence_refs: list of Decision Record IDs, log file paths, screenshots

model_version, prompt_hash (if applicable)

pre_state and post_state of Execution Agent (modes & counters)

signatures: approvals for reactivation (two custodians)

Store records under data/kill_switch_logs/ and include references in the main audit ledger.

Sample audit JSON:

{
  "action": "activate",
  "actor": "alice@example.com",
  "role": "operator",
  "timestamp_utc": "2025-12-16T13:05:00Z",
  "reason": "hallucination metric > 0.25",
  "evidence_refs": ["decision_20251216_001", "telemetry_20251216.json"],
  "model_version": "gpt-fin-2025-11-v3",
  "prompt_hash": "abcd1234",
  "pre_state": {"execution_mode":"live","live_order_count":3},
  "post_state": {"execution_mode":"shadow","live_order_count":0},
  "signatures": []
}
Testing & drills

Run a kill-switch drill quarterly. Steps:

Simulate telemetry trigger in staging.

Operator activates kill-switch.

Verify no live orders and audit entry recorded.

Reactivate following two-person procedure.

Produce drill report and store in data/kill_switch_drills/.

Document test schedule and responsible personnel.

Escalation & communication

On activation: immediate notification to Compliance, Security, Engineering, and custodians by the pre-defined alert channel (Slack/email/phone).

Prepare an internal incident statement and timeline. Coordinate external/regulatory communications with Compliance & Legal.

Post-incident obligations

Complete a formal post-mortem within the agreed SLA (typically 72 hours).

Update Addendum, CI checks, and tests to prevent recurrence.

Retain all artifacts for required regulatory retention period.

Implementation notes (operators/devs)

Prefer controlled operator-console toggles with strong authentication (2FA) and audit trail.

If using environment toggles or feature flags, protect them with IAM and review logs.

Ensure the Execution Agent honors the shadow and disabled states immediately and reliably.

Contacts

Security: security@example.com

Compliance: compliance@example.com

Ops lead: ops@example.com

Revision history

v1.0 — Initial kill-switch policy (YYYY-MM-DD)

  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -d '{"action":"activate","operator":"alice@example.com","reason":"hallucination spike"}'
