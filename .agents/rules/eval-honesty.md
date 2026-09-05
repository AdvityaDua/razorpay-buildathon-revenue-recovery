# Rule: Evaluation Honesty

This project's core credibility rests on honest, batch-level evaluation — not cherry-picked demo examples. Razorpay's own published evaluation bar for this track requires "measured money recovered across a batch," not a single good example. Violating this rule undermines the entire project's thesis, not just one metric.

## Rules

1. **Every metric reported anywhere (dashboard, eval report, pitch materials) must be computed over the full synthetic batch (300-500 records), never a hand-picked subset.** If a function only processes a subset for demo speed, it must be clearly labeled as a dev/debug shortcut and never wired into anything the eval report or dashboard actually displays.
2. **Ground truth (`true_root_cause`, `recoverable`, `amount_recoverable_if_acted_correctly`) must never be visible to the Diagnosis Agent or Recovery Policy Agent at inference time.** It exists only in `backend/eval/` for scoring after the fact. If you're writing agent code and you need to reference a `true_*` field, stop — that's a data leak into the system under test.
3. **Report failure modes, not just successes.** `backend/eval/metrics.py` must compute false diagnoses, self-consistency rate, and policy override count as first-class outputs, not optional extras. These numbers can look "bad" in isolation — that's fine and expected; they're part of an honest evaluation story, not something to hide or omit.
4. **The naive baseline (fixed-schedule retry) must run against the exact same batch as the system under test**, same records, same ground truth — never a different or easier subset.
5. **Any "policy override" event (where `validate_action()` overrode the LLM's proposed action) must be logged and counted**, not silently corrected. This number is evidence the guardrail works — treat it as a metric to report, not a bug to suppress.
