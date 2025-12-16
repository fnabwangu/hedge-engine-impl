# Security Policy

This repository follows a responsible-disclosure policy. If you discover a security vulnerability, please report it privately to the Security Contact below. Do **not** open an issue or post details publicly — doing so may expose users or enable exploitation.

---

## Security contact

Email: `security@your-domain.example`  
PGP (optional): `-----BEGIN PGP PUBLIC KEY BLOCK-----\n...replace-with-key...\n-----END PGP PUBLIC KEY BLOCK-----`

If you need to share sensitive files (logs, samples) encrypt them with the PGP key above or use a secure channel agreed in advance.

---

## What to include in a report

When reporting a vulnerability, include as much of the following as you can without sharing PII or production secrets:

- Short summary (1–2 lines).  
- Affected component(s) and paths (e.g., `src/execution_stub.py`, `API: /v1/orders`).  
- Software version or commit SHA where the issue was observed.  
- Environment details (OS, Python version, config flags) if relevant.  
- Step-by-step reproduction instructions (minimal repro).  
- Sample input/output or curl commands that reproduce the issue.  
- Log excerpts and stack traces (redact PII/credentials).  
- Estimated impact (data loss, RCE, financial exposure, disclosure).  
- Suggested mitigation (if you have one).  

**Do not** share private keys, credentials, PII, or live customer data in your initial report.

---

## How we handle reports

1. **Acknowledgement** — We will acknowledge receipt within **48 hours**.  
2. **Triage** — We aim to complete triage and assign severity within **5 business days**.  
3. **Remediation** — We will coordinate a plan (fix, mitigation, or workaround) and share timelines privately.  
4. **Disclosure** — We will coordinate public disclosure with the reporter: details and timeline will be agreed before publishing. Typical coordinated disclosure windows are **30–90 days** depending on severity and mitigation complexity.  
5. **Bounty/Recognition** — If you identify a substantive security issue and follow this policy, we will consider recognition or bounty on a case-by-case basis (not guaranteed).

---

## Severity classification (guideline)

- **Critical** — Immediate, practical ability to cause large financial loss, remote code execution in production, or leak of private keys/credentials. Requires immediate mitigation.  
- **High** — Serious vulnerability that could lead to significant impact (unauthorized trades, data exfiltration) but needs preconditions.  
- **Medium** — Vulnerability with limited impact or requiring difficult preconditions.  
- **Low** — Information disclosure with minimal impact, or best-practice issues.

Severity is determined by the project triage team and may change as new facts appear.

---

## Incident response (for operators)

If you detect an incident that may impact the Hedge Engine (model drift producing harmful trades, large unexpected slippage, suspicious execution activity, or data breach), follow this immediate checklist:

1. **Activate kill-switch** (if required): set `KILL_SWITCH=true` or use the Operator Console to switch the Execution Agent to shadow mode. This must be documented in the audit ledger immediately.  
2. **Stop new executions**: pause any automated order flows.  
3. **Snapshot & preserve**: capture Decision Records, execution logs, telemetry, and model version/prompt_hash. Preserve system snapshots for forensics.  
4. **Rotate credentials**: rotate any potentially affected service credentials (broker, data feeds, cloud keys).  
5. **Notify**: inform Compliance, Security, and the two kill-switch custodians. Use out-of-band channels if primary systems are compromised.  
6. **Triage & containment**: perform triage, contain the root cause, and apply hotfixes or mitigation.  
7. **Communicate**: prepare internal and (if required) external statements; coordinate with legal/compliance for regulatory notifications.  
8. **Post-mortem**: perform a root-cause analysis and publish a post-mortem internally; update Addendum and CI checks as needed.

---

## Safe harbor

If you are a security researcher following this policy (acting in good faith and within the law), we will not pursue legal action or demand source disclosure provided:

- You do not access or exfiltrate customer PII or production data beyond what is needed to demonstrate the issue.  
- You disclose the issue privately and do not publish details until coordinated with us.  
- You do not attempt to persist access or otherwise make the situation worse.

This safe harbor is not legal advice and does not grant permission to violate law or terms of service.

---

## Disclosure & public advisories

We will coordinate any public advisory with the reporter. Public disclosure will include:

- Summary of the issue, affected versions, and mitigations.  
- CVE identifier, if applicable.  
- Timeline of discovery, patching, and disclosure (redacted as necessary).  

We will not include customer-identifying data in public advisories.

---

## Regulatory & compliance escalation

If the incident potentially triggers regulatory reporting obligations (e.g., material financial loss, data breach), Compliance will lead external reporting and notify regulators as required. Security must keep Compliance and Legal informed at all stages.

---

## Contact and escalation

Security email: `security@your-domain.example`  
If you do not receive an acknowledgement within 48 hours, escalate to: `security-escalation@your-domain.example` or call the Security contact listed above.

---

## Revision history

- v1.0 — Initial policy (YYYY-MM-DD)

---

**Note:** This SECURITY.md is a project policy file — tailor names, emails, PGP keys, timelines, and legal language to your organization before publishing.
