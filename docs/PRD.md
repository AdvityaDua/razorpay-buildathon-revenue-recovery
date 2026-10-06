# PRD — AI Recurring Revenue Recovery Orchestrator

**payment gateway Buildathon — Track 03: AI Revenue Recovery**
**Timeline:** 5 build days (Aug 28 – Sep 5, 2026) · **Submission-ready target:** Sep 5
**Status:** Locked scope. Build against this document — do not silently expand scope mid-build.

---

## 1. One-paragraph summary

An AI agent that sits between a failed recurring payment (subscription/mandate auto-debit) and a merchant's recovery workflow. It diagnoses *why* the payment failed from structured evidence (not a blind retry), scores its own confidence, selects the recovery action with the best expected value under a **deterministic, non-overridable compliance policy layer**, executes it in simulation, and reports honest batch-level metrics — diagnosis accuracy, ₹ recovered, retries avoided, and cases correctly stopped — against a naive fixed-schedule retry baseline.

---

## 2. Problem statement (final, approved)

Every subscription or recurring-payment business on payment gateway relies on auto-debit mandates succeeding every billing cycle. When a payment fails, the failure code alone rarely explains why — it could be insufficient funds, an expired mandate, a missed step-up authentication, a bank-side decline, or the customer deliberately cancelling the mandate. Treating every failure the same way (retry N times on a fixed schedule) is inefficient, and in the cancelled-mandate case, actively disrespects customer intent and RBI/network compliance rules around mandate revocation and the mandatory 24-hour pre-debit notice window.

Merchants often lack a sufficiently context-aware way to understand why a payment failed, whether it's recoverable, what intervention has the best expected return, and when to stop. This produces silent, compounding revenue loss.

## 3. Solution summary (final, approved)

Two-stage agent:

1. **Diagnosis Agent** — reasons over failure code, timing (vs. pre-debit alert), mandate status/history, and customer payment behavior to produce a structured root-cause diagnosis with a confidence score and cited evidence. Must degrade gracefully when structured error fields are null (confirmed to happen in real payment gateway payloads).
2. **Recovery Policy Agent** — takes the diagnosis and selects the action with the best expected recovery value (`Expected Revenue Recovered − Cost of Intervention − Customer Friction Cost − Risk/Compliance Penalty`), bounded by a **deterministic policy layer** that hard-gates STOP conditions (e.g., customer-cancelled mandate) — the LLM cannot override these regardless of what it outputs.

Every decision is logged to a full audit trail. The system is evaluated on a synthetic batch (300–500 records) with known ground truth against a naive retry baseline, reporting precision/recall, ₹ recovered, false diagnoses, unnecessary retries avoided, and % correctly stopped.

**Positioning:** this is an intelligence layer on top of payment gateway's existing infrastructure (webhooks, subscriptions API, native retry mechanism), not a replacement for it.

---

## 4. Scope — MVP vs. Stretch (locked for 5-day build)

### 4.1 MVP — must ship

| Component | Included |
|---|---|
| Synthetic dataset | 300–500 labeled failure records, realistic distribution, ~20-30% ambiguous/noisy cases |
| Diagnosis Agent | LangGraph node, structured output via tool-calling, evidence-grounded reasoning, calibrated confidence |
| Deterministic policy/compliance layer | Rule table (Section 7) — hard STOP conditions, action eligibility per diagnosis |
| Recovery Policy Agent | Selects action from policy-permitted set, computes expected value |
| Simulated action execution | No real payments/messages sent — simulated outcome resolution against ground truth |
| Audit trail | Structured log per record: evidence → diagnosis → confidence → policy check → action → outcome |
| Batch evaluation harness | Runs full batch, computes all metrics vs. baseline, outputs a report |
| Baseline comparator | Naive fixed-schedule retry logic (mirrors payment gateway's documented default behavior) |
| Merchant dashboard (frontend) | Recovery queue view + aggregate metrics view (Section 8) |
| Backend API | FastAPI serving dashboard + triggering batch runs |

### 4.2 Explicitly OUT of scope for MVP (stretch / mention-only in pitch)

- Voice agent / Hinglish voice recovery
- Real WhatsApp/SMS sending (simulate the notification content + a mocked "delivered" state instead)
- Low-confidence structured follow-up flow (human-review queue / customer prompt) — **mention as designed-for extension point in architecture, do not build the actual flow**
- Celery / distributed task queue — not needed at this scale; mention as a scaling note only
- Real payment gateway live-mode integration — test-mode webhook shapes only, used to validate schema realism
- RAG over historical cases (Qdrant is available but not required — stretch only if time remains after MVP)
- Authentication/multi-tenant merchant accounts — single demo merchant only

### 4.3 Cut lines if time runs short (in order of what to drop first)

1. Drop dashboard polish → tabular/simple UI is acceptable, functionality > visual design
2. Drop baseline comparator UI display → keep the metric computed and reported, just not visualized
3. Reduce batch size from 500 → 300 (do not go below ~200, credibility of "batch" claim depends on this)
4. Drop the second (easy-case) prompt-validation test suite → keep only the core eval harness

---

## 5. Users / personas

- **Primary demo persona:** an ops/finance user at a subscription-based merchant (e.g., SaaS or OTT business) using payment gateway Subscriptions. This is who the dashboard is designed for.
- **Panel/evaluator (real audience):** technical reviewers assessing agentic reasoning quality, honest evaluation methodology, and compliance-aware system design — not the end merchant. Every metric and audit-trail view should be legible to this audience.

---

## 6. Data model

### 6.1 Failure record schema (per synthetic record)

```
mandate_id: string
customer_id: string
merchant_id: string
amount: number (INR)
mandate_type: enum [upi_autopay, nach, card_emandate]
scheduled_debit_at: datetime
actual_attempt_at: datetime
pre_debit_notification_sent_at: datetime | null

error_code: string | null          # realistically null ~30-40% of the time
error_reason: string | null
error_source: string | null
error_step: string | null

mandate_status: enum [active, paused, revoked, expired]
mandate_created_at: datetime
mandate_validity_days: number

customer_prior_successful_payments: int
customer_prior_failures: int
customer_last_payment_date: date | null
retry_attempt_number: int

# GROUND TRUTH (not visible to the agent — used only for evaluation)
true_root_cause: enum [insufficient_funds, mandate_expired, afa_required, customer_cancelled, genuine_decline, ambiguous]
recoverable: bool
true_recovery_action: string | null
amount_recoverable_if_acted_correctly: number
```

### 6.2 Root-cause taxonomy (locked)

| Cause | Definition | Compliance implication |
|---|---|---|
| `insufficient_funds` | Temporary balance shortfall | Retry-eligible, timing matters |
| `mandate_expired` | Mandate validity period lapsed | Needs re-authorization, not retry |
| `afa_required` | Amount crossed no-auth threshold (~₹15,000), step-up auth not completed | Needs step-up nudge, not blind retry |
| `customer_cancelled` | Customer paused/revoked mandate | **Hard STOP — no retry, no exception** |
| `genuine_decline` | Explicit bank/network technical decline, evidenced by a non-null error signal | Method-dependent recovery (e.g., ask for alternate payment method) |
| `ambiguous` | No cause positively supported by evidence | Route to low-confidence path (stretch); MVP = flag and hold, don't act |

### 6.3 Synthetic data generation approach

- Anchor distribution loosely on real reported Indian autopay/e-mandate failure-reason breakdowns (cite in dataset README).
- Deliberately null out error fields in ~30% of records to mirror confirmed real-world payment gateway webhook behavior.
- Inject genuinely ambiguous cases (conflicting or absent secondary signals) at ~20-30% of the batch — this is what makes the eval meaningful, not decorative.
- Ground truth (`true_root_cause`, `recoverable`, `amount_recoverable_if_acted_correctly`) generated alongside each record at creation time, never derived from the agent's own output.

---

## 7. Deterministic policy / compliance layer (locked rule table)

This layer sits **between** the Recovery Policy Agent's LLM output and actual execution. It is pure code (no LLM), and it can only narrow or block the LLM's chosen action — never expand it.

| Condition | Rule | Overridable by LLM? |
|---|---|---|
| `mandate_status == revoked` OR diagnosis == `customer_cancelled` | Hard STOP. No retry, no notification. Log and exit. | **No — never** |
| `mandate_status == paused` | Hard STOP for this cycle. May re-check next cycle. | **No** |
| Diagnosis == `ambiguous` | No automated recovery action. Flag for review (simulated). | **No** |
| Diagnosis confidence < 0.5 | Treat as `ambiguous` regardless of stated root_cause. | **No** |
| `retry_attempt_number >= 3` for same billing cycle | Hard STOP — do not retry again this cycle, matches payment gateway's own halt-after-exhaustion behavior. | **No** |
| `amount > 15000` AND diagnosis != `afa_required` confirmed | Action restricted to re-auth/step-up flow only, not blind retry. | **No** |
| Diagnosis == `mandate_expired` | Action restricted to re-authorization link only. Retry action blocked at code level even if LLM proposes it. | **No** |
| Diagnosis == `insufficient_funds`, confidence >= 0.5 | LLM may choose retry timing within policy-allowed window (e.g., +1 to +5 days). | Timing only, within bounds |
| Diagnosis == `genuine_decline` | Action restricted to alternate-payment-method prompt, no blind retry. | **No** |

**Design principle to preserve in code:** the LLM proposes an action + reasoning; a pure-function `validate_action(diagnosis, proposed_action, context) -> allowed_action` call is what actually executes. If `proposed_action` violates a hard rule, `validate_action` substitutes the safe fallback and logs the override event explicitly (this override-log is itself a good metric: "# times policy layer overrode LLM proposal").

---

## 8. System architecture

### 8.1 Stack (locked)

- **Backend:** FastAPI
- **Agent orchestration:** LangGraph (LangChain for LLM interface)
- **LLM:** NVIDIA Nemotron, OpenAI-compatible endpoint, native tool-calling enabled
- **Frontend:** React + ShadCN + TanStack Query (not Redux)
- **Data storage:** simple — synthetic dataset as JSON/CSV or lightweight SQLite/Postgres; no need for anything heavier at this scale
- **Background/async:** none required for MVP; Celery explicitly out of scope (see 4.2)

### 8.2 LangGraph node structure

```
[failure_event] 
     ↓
[Diagnosis Node]  — LLM call, structured output (Section 9 schema)
     ↓
[Confidence Gate] — pure code: confidence < 0.5 or ambiguous → route to HOLD
     ↓                                                              ↓
[Policy Node]      — pure code: applies Section 7 rule table   [HOLD / logged, no action]
     ↓
[Recovery Policy Agent Node] — LLM proposes action + timing, within policy-allowed set
     ↓
[validate_action()] — pure code, final hard gate, can override LLM proposal
     ↓
[Simulated Execution Node] — resolves outcome against ground truth (for eval only)
     ↓
[Audit Log Node] — writes full trail entry
```

This graph runs once per failure record during batch evaluation. Each node's input/output is logged for the audit trail regardless of pass/fail.

### 8.3 Repo structure (suggested, adjust as needed)

```
/backend
  /agent
    diagnosis_node.py
    policy_rules.py        # Section 7 table as code, pure functions
    recovery_node.py
    graph.py                # LangGraph graph definition
  /data
    generate_synthetic.py
    schema.py                # Pydantic models, Section 6.1
    dataset.json
  /eval
    run_batch.py
    baseline.py              # naive fixed-schedule retry comparator
    metrics.py
  /api
    main.py                  # FastAPI app
    routes/
  llm_client.py               # ChatOpenAI pointed at NVIDIA Nemotron gateway
/frontend
  /src
    /components
    /pages
      RecoveryQueue.tsx
      Metrics.tsx
    /api                      # TanStack Query hooks
/docs
  PRD.md                      # this file
  data_coverage_table.xlsx
  architecture_diagram.*
```

---

## 9. Diagnosis Agent — output schema (locked, tested)

```python
class CauseEvaluation(BaseModel):
    cause: Literal["insufficient_funds", "mandate_expired", "afa_required",
                   "customer_cancelled", "genuine_decline"]
    verdict: Literal["ruled_out", "plausible"]
    reason: str  # must cite specific input field(s)

class Diagnosis(BaseModel):
    cause_evaluations: List[CauseEvaluation]  # all 5 non-ambiguous causes, evaluated
    root_cause: Literal["insufficient_funds", "mandate_expired", "afa_required",
                         "customer_cancelled", "genuine_decline", "ambiguous"]
    confidence: float  # 0-1
    evidence: str  # must cite specific field names/values, not generic restatement
```

**Validation rule (enforced in code, not just prompt):** `root_cause` must equal a `cause` marked `plausible` in `cause_evaluations`, or be `ambiguous`. Reject/retry the LLM call if this invariant is violated — this was a confirmed real failure mode during testing (see Section 12).

**System prompt requirements (tested, see Section 12 for validation results):**
- Mandatory reasoning procedure: evaluate all 5 causes individually before selecting
- `genuine_decline` may only be `plausible` if a non-null error signal exists — absence of error fields is not evidence for a specific technical cause
- Confidence calibration tiers explicitly defined (≥0.8 requires 2+ independent agreeing signals; <0.5 default for weak/generic evidence)
- Known residual gap: model sometimes marks a cause `plausible` via elimination rather than positive support — track `self_consistency_rate` and spot-check this in eval, do not assume the rubric fully closes it

---

## 10. Evaluation plan

### 10.1 What's compared

- **System under test:** two-stage agent (Diagnosis + Policy) with deterministic gate
- **Baseline:** naive fixed-schedule retry (mirrors payment gateway's documented default: retry next day, shift for holidays, halt after exhaustion — no diagnosis, no differentiation by cause)

### 10.2 Metrics (all computed on the full batch, none cherry-picked)

| Metric | Definition |
|---|---|
| Diagnosis precision/recall | Per root-cause class, against `true_root_cause` |
| Self-consistency rate | % of records where `root_cause` is a valid member of `plausible` causes |
| Confidence calibration | Binned confidence vs. actual accuracy in that bin (reliability plot) |
| ₹ recovered (system) | Sum of `amount` for records where correct action → simulated recovery succeeds |
| ₹ recovered (baseline) | Same, using naive retry logic only |
| Unnecessary retries avoided | Count of `customer_cancelled` / hard-stop cases where system correctly took no action vs. baseline retrying anyway |
| False diagnoses | Count where `root_cause` ≠ `true_root_cause`, broken down by class |
| % correctly stopped | Of all true hard-stop cases, % where system correctly produced STOP |
| Policy override count | # times `validate_action()` overrode the LLM's proposed action (this is a *feature*, not a bug — report it as evidence the guardrail works) |

### 10.3 Output artifact

`eval/run_batch.py` produces a single JSON/CSV report + a summary printed to console. Frontend Metrics page reads this report — no need for real-time computation on every dashboard load.

---

## 11. Frontend — pages (MVP scope only)

### 11.1 Recovery Queue page
- Table/list of failure records from the batch run
- Per record: diagnosis (root_cause + confidence), evidence summary, action taken or STOP reason, outcome
- Filter/sort by diagnosis class or action type is a nice-to-have, not required

### 11.2 Metrics page
- Headline numbers: ₹ recovered (system vs. baseline), recovery rate %, % correctly stopped
- Diagnosis precision/recall table
- Confidence calibration chart (optional if time-constrained — can ship as a static image from the eval script instead of a live chart)

**No auth, no multi-merchant switching, no settings pages for MVP.**

---

## 12. Findings from live testing (carry into build — do not re-litigate)

Confirmed via direct testing against the deployed NVIDIA Nemotron endpoint:

1. Real payment gateway `payment.failed` webhook payloads can have `error_reason`, `error_source`, `error_step` all `null` — the Diagnosis Agent must handle this as the common case, not the edge case.
2. Native tool-calling requires correct configuration on the launch command — confirmed working after this fix.
3. Without an explicit reasoning-procedure schema (Section 9's `cause_evaluations` structure), the model would select a `root_cause` it had never evaluated or had already ruled out — a real, reproduced bug, fixed by forcing structured per-cause evaluation.
4. Even with the fix, the model can still mark a cause `plausible` by elimination rather than genuine positive support in ambiguous cases. This is a known, documented residual limitation — build the self-consistency metric to track it rather than assuming the prompt fully solves it.
5. Confidence calibration instructions in the system prompt measurably changed model behavior (dropped from an unjustified 0.7 to an honest 0.4-0.5 on weak evidence) — worth keeping and citing as evidence of deliberate calibration work in the pitch.

---

## 13. Pitch / submission checklist (per payment gateway's own requirements)

- [ ] Track: AI Revenue Recovery (Track 03)
- [ ] Project name
- [ ] What it solves — pull from Section 2/3
- [ ] Public GitHub repo URL
- [ ] 5-minute pitch video (unlisted OK)
- [ ] "What broke, and how you got out" — use Section 12 findings directly, this is a gift, don't waste it
- [ ] Explicitly state in pitch: honest batch metrics (not cherry-picked), compliant hard-stop rules, full audit trail — these map directly to their published "bar" language

---

## 14. Open questions / decide during build

- Exact confidence threshold for the HOLD/ambiguous gate (0.5 is a starting point, may need tuning after seeing batch results)
- Whether the "policy override count" metric changes your pitch narrative if it's very high (may indicate the LLM's proposals are frequently unsafe) or near-zero (may indicate the gate is rarely tested) — either result is a legitimate finding, be ready to discuss it either way
- Final call on whether confidence calibration chart ships as live component or static image (Section 11.2) — decide based on time remaining after core batch eval works end-to-end
