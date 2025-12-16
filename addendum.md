```markdown
# Implementation Addendum — Hedge Engine

**Purpose**  
This Addendum is the canonical, auditable implementation specification for the Hedge Engine developer kit. It maps the e-book’s conceptual rules to concrete repo artifacts and operator procedures. Keep this file current: any change to prompts, `model_version`, EV gates, risk parameters or kill-switch logic requires an update to this Addendum, a changelog entry, and compliance signoff.

Operator contacts:
- Engineering lead: NAME <eng@example.com>
- Compliance lead: NAME <compliance@example.com>
- Security contact: NAME <security@example.com>

Kill-switch custodians (two-person required):
- Custodian A: NAME <a@example.com>
- Custodian B: NAME <b@example.com>

---

## Scope & intent

This Addendum covers:

- implementation manifest (what files must exist and where)  
- Decision Record contract and JSON schema  
- research→writing prompt contract and schema  
- deterministic numeric gates and risk rules  
- sandbox execution contract and operator runbook  
- audit, replay and release procedures (including checksums and `prompt_hash`)  
- CI, tests and minimal publishing requirements  
- compliance and kill-switch policy

This document is the policy. Companion artifacts (schemas, validator, dataset manifest, scripts) implement and validate the policy.

---

## Canonical repository manifest

The repository must contain these artifacts at minimum:

```

README.md
LICENSE
CONTRIBUTING.md
CHANGELOG.md
ADDENDUM.md            # this file
.gitignore
.gitattributes
.github/workflows/ci.yml
prompts/
research_prompt.json
signal_template.json
schemas/
decision_record.json
src/
decay_sim.py
ev_calc.py
pretrade_checks.py
risk_engine.py
execution_stub.py
audit.py
cli.py
data/
generate_sandbox_data.py
sandbox_etf_prices.parquet
sandbox_letf_navs.parquet
event_calendar.csv
decision_records/         # append-only decision records
scripts/
validate_addendum.py
run_sandbox.py
run_backtest.py
notebooks/
tests/
manual/
source/
pdfs/
full-manual-optimized.pdf
dataset_manifest.json

```

Large binaries (full manual, datasets) must be Release assets or tracked with Git LFS — do **not** embed multi-GB binaries in git history. Keep prompt text and schemas under `prompts/` and never alter historical prompt files without recording `prompt_hash` and shadow-run results.

---

## Architecture (high level)

```

[Data Layer] -> [Signal Layer (LLM)] -> [Decision Engine] -> [Execution Agent]
|               |                        |                  |
v               v                        v                  v
[Market/Event Feeds] [Research→Writing]  [EV gate, Risk Engine] [Sandbox / Live Broker]
↘
[Audit Ledger]
↘
[Operator Console / Kill-Switch]

````

Responsibilities

- Data Layer: produce frozen `market_snapshot`, `macro_indicators`, `options_skew`, `event_calendar`, `ptr_summary`. Store snapshots for audit.  
- Signal Layer: run the research prompt and return only structured JSON per `prompts/signal_template.json`.  
- Decision Engine: deterministic `ev_calc`, LETF decay, `pretrade_checks`, `risk_engine` sizing, `viability_pass` gate, and `execution_plan` generation.  
- Execution Agent: sandboxed `execution_stub` for testing and a gated live broker adapter for production.  
- Audit Ledger: append-only Decision Records with `prompt_hash`, `model_version`, evidence, and an `audit_hash`.

---

## Decision Record — canonical contract

Every decision must produce a Decision Record JSON with at minimum:

```json
{
  "decision_id": "uuid",
  "timestamp_utc": "2025-12-16T12:00:00Z",
  "model_version": "provider_model_identifier",
  "prompt_hash": "sha256-of-prompt",
  "inputs": { "market_snapshot": {}, "macro_indicators": {} },
  "llm_output": {},
  "quant_checks": { "ev_gross": 0.0, "letf_decay": 0.0, "ev_net": 0.0, "viability_pass": true },
  "human_review": { "required": false, "reviewer_id": null, "approval": null },
  "execution_plan": {},
  "execution_result": {},
  "evidence": [ { "source_id":"", "type":"", "filecite":"", "excerpt":"" } ],
  "audit_hash": "sha256",
  "signature": { "signed_by":"", "signature_hash":"", "signed_at":"" }
}
````

Audit rules

* `prompt_hash` = SHA-256 of the exact prompt text used (system + user + examples). Keep prompt files in `prompts/`.
* `audit_hash` = SHA-256 of a canonical JSON serialization of the Decision Record **excluding** `audit_hash` and `signature`. Implement `src/audit.compute_audit_hash()` accordingly.
* For any signal with `p_confidence >= 0.7` include **at least two** distinct evidence items (different `source_id`).
* If `viability_pass == false`, **do not** execute automatically.

---

## Prompt contract — research → writing

The canonical system message lives in `prompts/research_prompt.json`. The LLM must:

* Output **only** structured JSON matching `prompts/signal_template.json`.
* Provide `decision_id`, `timestamp_utc`, `prompt_hash`, and `model_version`.
* For `p_confidence >= 0.7` include at least two evidence items (`source_id`, `type`, `filecite`, `excerpt`), excerpts ≤ 200 chars.
* For visualizations return `chart_spec`; deterministic renderer produces PNGs.
* Limit `manuscript_snippet` to ≤ 300 words.

Prompt-change procedure

```text
1) Add new prompt file prompts/research_prompt_vX.json and compute prompt_hash.
2) Run shadow-run (>=7 days or historical event suite). Collect calibration metrics: p_success reliability, viability_pass rate, evidence completeness.
3) Attach shadow-run report to PR. Obtain compliance sign-off before merging or allowing live execution.
```

---

## Deterministic numeric gates & risk rules

EV Gate (deterministic)

```
ev_gross = p_success * fav + (1 - p_success) * unfav
letf_decay = max(0, -mean(decay_sim_results))
ev_net = ev_gross - letf_decay - trading_costs - slippage
viability_pass = (ev_net > safety_margin) AND (p_confidence >= 0.7)
```

Defaults and practices

* Default `safety_margin` = 0.01 (1%). Store intermediate values in `quant_checks`.
* LETF decay must be computed via `simulate_lef_decay()` with a fixed RNG seed; store `trials` and `seed`.
* Compute `T_max = compute_t_max(leverage, est_vol_annual)`. If `horizon_days > T_max` set `flags.requires_human_review = true`.
* Use `compute_scale_factor(target_vol, returns)` for sizing. Clamp between `min_scale` and `max_scale`.
* Compute 1-day 99% parametric VaR as baseline; historical VaR as alternative. Ensure portfolio VaR stays below configured limit.
* Emergency drawdown default: 10% P2T. On trigger reduce exposure to `min_exposure_floor = 0.3` and notify operators.

---

## Execution & sandbox

* Sandbox: `src/execution_stub.py` must accept `execution_plan` + `market_snapshot`, simulate seeded deterministic fills, respect SOR (`percent_of_adv`), TWAP, and `max_slippage_bps`. Return fills and metrics.
* Live: broker wrappers must be gated by two-person approval and compliance. Store secrets in vault/CI secrets.
* Default SOR policy: `percent_of_adv = 0.05`. Abort if projected slippage > `max_slippage_bps`.

---

## Audit, replay & validation

* `src/audit.py` must provide `make_decision_record()`, `compute_audit_hash()`, `save_decision_record()` and `replay_decision()` that re-run deterministic checks and report mismatches.
* Decision Records stored append-only under `data/decision_records/`.
* Replays must verify `audit_hash` and numeric reproducibility within tolerance (EV, LETF decay with same seed).

Sample audit-hash computation (CLI)

```bash
# compute prompt hash
sha256sum prompts/research_prompt.json | awk '{print $1}'

# compute artifact sha
sha256sum manual/pdfs/full-manual-optimized.pdf
```

---

## Operator runbook

Local sandbox

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python data/generate_sandbox_data.py
python scripts/run_sandbox.py full
```

Shadow live (paper)

* Connect real-time feeds, keep execution in shadow mode, run 30–90 days, validate `p_success` calibration and hallucination metrics.

Small live

* Start with low notional (e.g., max $50k/trade). Human approval for LETF trades with `horizon_days > 7`. Continuous monitoring.

Kill-switch

```text
Activation:
- Detect emergency (hallucination spike, slippage spike, emergency_drawdown)
- Operator toggles KILL_SWITCH -> Execution Agent enters shadow mode
- Record time, model_version, prompt_hash, relevant Decision Records
- Notify Compliance & Security
Reactivation:
- Two custodians must both sign (recorded in audit ledger) to re-enable live execution
```

---

## CI & tests

* CI must run `pytest`, `nbval` for notebooks, `flake8`, `black` checks, and `scripts/validate_addendum.py --update`.
* On tag `v*`, CI builds reproducible artifacts and uploads them as Release assets; include `prompt_hash` and `model_version` in release notes.

CI step example

```yaml
- name: Validate Addendum
  run: python scripts/validate_addendum.py --update
```

---

## Release & provenance

Release checklist

```
- Tag repo: git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push --tags
- Build artifacts (zip, PDF) via CI for reproducibility
- Compute SHA256 for artifacts:
  sha256sum hedge-engine-impl-vX.Y.Z.zip
  sha256sum manual/pdfs/full-manual-optimized.pdf
- Draft GitHub Release vX.Y.Z and attach artifacts; include:
  * prompt_hash (sha256)
  * model_version
  * dataset_manifest.json checksums
  * artifact SHA256 checksums
  * compliance sign-off
```

Release notes template

```
Release vX.Y.Z
- prompt_hash: <sha256>
- model_version: <provider/model@date>
- artifacts:
  - hedge-engine-impl-vX.Y.Z.zip  SHA256: <sha256>
  - manual/pdfs/full-manual-optimized.pdf  SHA256: <sha256>
- dataset_manifest: refer to dataset_manifest.json
- compliance_signoff: NAME (compliance) <date>
```

---

## Compliance & disclosure

```
RISK DISCLOSURE:
This Implementation Addendum and related artifacts are for educational and research purposes and do NOT constitute investment, legal or regulatory advice. Use of leveraged ETFs and derivatives carries risk of rapid and permanent loss. LLM outputs may hallucinate; all probabilistic recommendations must be validated by deterministic gates and human oversight. Live deployment requires legal and compliance sign-off.
```

Operator sign-off checklist before live

* Legal counsel approval: yes / no
* Compliance policy signed: yes / no
* KYC/AML procedures in place: yes / no
* Insurance / institutional custody: yes / no
* Kill-switch custodians (two persons) documented: names & contacts

---

## Appendix — schemas & manifests

Decision Record schema

```json
{
  "type":"object",
  "properties":{
    "decision_id":{"type":"string"},
    "timestamp_utc":{"type":"string"},
    "model_version":{"type":"string"},
    "prompt_hash":{"type":"string"},
    "llm_output":{"type":"object"},
    "quant_checks":{"type":"object"},
    "execution_plan":{"type":"object"},
    "audit_hash":{"type":"string"}
  },
  "required":["decision_id","timestamp_utc","prompt_hash","model_version","llm_output","quant_checks","audit_hash"]
}
```

Dataset manifest example

```json
{
  "files":[
    {"path":"manual/pdfs/full-manual-optimized.pdf","sha256":"<paste-sha256-here>"},
    {"path":"data/sandbox_etf_prices.parquet","sha256":"<paste-sha256-here>"},
    {"path":"data/sandbox_letf_navs.parquet","sha256":"<paste-sha256-here>"}
  ]
}
```

Validator reference

```text
scripts/validate_addendum.py
Run: python scripts/validate_addendum.py --fix --update
CI must run the validator on PRs and on push to main.
```

Keep this Addendum synchronized with code and release artifacts. Any change to prompts, `model_version`, deterministic gates, or execution logic must be accompanied by tests, a shadow run or backtest proof, a `CHANGELOG.md` entry, and explicit compliance sign-off before enabling larger or live execution.

```
```
