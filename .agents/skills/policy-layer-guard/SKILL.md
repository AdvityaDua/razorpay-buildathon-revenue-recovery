---
name: policy-layer-guard
description: Use this skill whenever writing, editing, or reviewing code that touches the deterministic policy/compliance layer, the validate_action() function, recovery action execution, or any code path where an LLM's output could result in a payment retry or customer-facing action being triggered. Also use when writing or modifying the Recovery Policy Agent node, the policy rule table, or any STOP-condition logic. Trigger on file paths matching backend/agent/policy_rules.py, backend/agent/recovery_node.py, or any code implementing PRD Section 7.
---

# Policy Layer Guard

## Why this skill exists

The entire product thesis of this project is that a deterministic, non-LLM policy layer gates every recovery action — the LLM proposes, code disposes. This was a deliberate architectural decision made after live-testing showed the LLM can be confidently wrong (see PRD Section 12). If this boundary gets blurred during implementation — e.g., an LLM's structured output field gets executed directly "just this once" for convenience — the project's core defensible claim collapses, and this is exactly the kind of thing a technical reviewer will probe for.

## Rules to enforce in any code you write or review here

1. **`validate_action()` must be a pure function**: `(diagnosis: Diagnosis, proposed_action: Action, context: FailureRecord) -> AllowedAction`. No LLM calls inside it, no network calls, no randomness. It must be fully unit-testable with hardcoded inputs and deterministic expected outputs.
2. **Every row in PRD Section 7's rule table must have a corresponding, individually testable branch** in `policy_rules.py`. When implementing, write the rule table as a literal ordered sequence of checks (first-match-wins or explicit priority), not a single sprawling conditional. Each rule should be traceable back to its row in the PRD table via a code comment.
3. **Hard-stop conditions (`mandate_status == revoked`, `customer_cancelled` diagnosis, `mandate_status == paused`, `retry_attempt_number >= 3`, confidence < 0.5) must be checked BEFORE any LLM-proposed action is considered**, and if triggered, must short-circuit — no downstream code path should be able to execute an action after a hard-stop condition matched, regardless of what the LLM proposed.
4. **Never let `proposed_action` flow directly into an execution function.** The only permitted flow is: LLM proposes → `validate_action()` returns an `AllowedAction` (which may differ from the proposal) → execution function consumes only the `AllowedAction`. If you find yourself writing `execute(llm_output.action)` anywhere, stop — that's the bug this skill exists to prevent.
5. **Log every override.** When `validate_action()` returns something different from what was proposed, write an explicit audit trail entry noting both the original proposal and the substituted action, with the rule that triggered the override. This is a reportable metric (PRD Section 10.2), not just internal bookkeeping.
6. **When in doubt about a new rule not explicitly in PRD Section 7, default to STOP, not to action.** The cost of an incorrectly withheld recovery is a missed retry; the cost of an incorrect action against a hard-stop case (e.g., retrying a cancelled mandate) is a compliance violation. These are not symmetric — bias the fallback toward safety.

## Quick self-check before finishing any change here

- Can this function be called with a hardcoded `Diagnosis` + `Action` + no LLM/network access, in a unit test, and produce a deterministic result? If not, something's wrong.
- Does every hard-stop condition from PRD Section 7 have a corresponding test case with that exact condition triggered?
- If the LLM proposed an unsafe action, does the test suite prove it gets overridden, not just that a "safe" input passes?
