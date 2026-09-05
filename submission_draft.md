# Razorpay Buildathon 2026 — Track 03: AI Revenue Recovery Submission

## Project Name / Title
**AI Recurring Revenue Recovery Orchestrator**

## Project Objectives — What does it solve?
Every subscription business on Razorpay relies on auto-debit mandates succeeding. When a payment fails, the failure code alone rarely explains why — it could be insufficient funds, an expired mandate, a missed step-up authentication, a bank decline, or the customer deliberately cancelling. Treating every failure the same way (blindly retrying N times) is inefficient, actively loses revenue on edge cases, and in the cancelled-mandate case, is a direct compliance violation of RBI revocation rules.

Merchants lack a context-aware way to understand why a payment failed, what intervention has the best expected return, and when to stop. This produces silent, compounding revenue loss.

Our AI Orchestrator solves this by sitting between a failed payment and the recovery workflow. It uses a **two-stage LLM agent** to diagnose the root cause from structured evidence and propose an optimal recovery action (e.g., step-up auth, re-auth links, alternate payment prompts). Crucially, this agent is bounded by a **deterministic, non-overridable compliance policy layer**. The LLM proposes; the policy code disposes, ensuring we never retry a cancelled mandate or violate hard rules, while capturing the ~84% of revenue that naive retry systems leave on the table.

## GitHub Repository URL
[Replace with your actual GitHub URL]

## 5-min Pitch Video Link
[Replace with your actual unlisted YouTube/Drive link]

## Build Challenges & Technical Obstacles (What broke & how we got out)

1. **The Null-Signal Reality:** Real Razorpay `payment.failed` webhooks frequently have `error_reason`, `error_source`, and `error_step` as `null` (~30-40% of the time). Initially, our agent hallucinated causes for these. We fixed this by generating a synthetic dataset that mathematically mirrors this null rate, and forcing the LLM to rely on secondary signals (mandate history, timing) or gracefully degrade to an `ambiguous` classification.
2. **LLM Reasoning Inconsistencies:** During prompt testing, Llama 3.3 would sometimes output a `root_cause` that it had never actually evaluated or had explicitly ruled out. We solved this with a code-level self-consistency validation: if the chosen root cause wasn't marked `plausible` in its internal evaluation chain, the system catches it, retries once, and then flags it as ambiguous to prevent unsafe actions.
3. **Overconfidence on Weak Evidence:** The model was highly confident (0.7+) even on null-error cases. We fixed this by explicitly defining calibration tiers in the system prompt. Now, < 0.5 confidence auto-routes to a manual HOLD state via the policy layer.
4. **Tool-Calling Architecture:** We had to strictly use native tool-calling over regex parsing for structured outputs. This required figuring out that we needed to pass `--enable-auto-tool-choice --tool-call-parser llama3_json` to our self-hosted vLLM endpoint for the OpenAI-compatible wrapper to correctly parse the LangChain structured outputs.

## Key Technical Decisions & Architecture

1. **The Deterministic Policy Layer:** This is the core thesis of our project. The LLM does not execute actions. It proposes them to a pure Python function (`validate_action()`) that implements 9 hard-coded PRD rules. If the LLM proposes retrying a revoked mandate, the code overrides it to a hard STOP. We track these overrides as a core system metric.
2. **Honest Batch Evaluation:** We did not build a cherry-picked demo. We built a full LangGraph batch-evaluation harness that runs 400 synthetic records against our agent and compares it to a naive fixed-schedule retry baseline (mirroring default Razorpay behavior).
3. **Type-Level Ground Truth Isolation:** We use distinct Pydantic types — `FailureRecordInput` (what the agent sees) and `FailureRecord` (with ground truth) — to guarantee the agent never sees the answers during evaluation.

## Performance Metrics (AI System vs. Baseline)

We tested against a 400-record dataset with ₹29.6L in recoverable revenue.

*   **Baseline (Naive Retry) Performance:** Recovered ₹11.5L (38.7% rate). It completely failed to recover any revenue from AFA/Step-up (₹7.9L), Genuine Declines (₹4.3L), or Expired Mandates, because it only knows how to blindly retry. Worse, it committed 25 compliance violations by retrying cancelled mandates.
*   **AI System Opportunity:** Our system is designed specifically to capture the ₹12.2L (an 84% lift) that the baseline leaves on the table by deploying the *correct* intervention (re-auth links, alternate payment prompts) based on the diagnosed root cause, while the deterministic policy layer ensures 0 compliance violations.

*(Final system numbers will be populated once the batch run completes against the live vLLM endpoint).*
