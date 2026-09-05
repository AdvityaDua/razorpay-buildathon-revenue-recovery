---
name: eval-harness-conventions
description: Use this skill when writing or editing code in backend/eval/, including the batch runner, baseline comparator, or metrics calculations, or when generating synthetic data in backend/data/ that will be used for evaluation. Also use when building the Metrics page on the frontend, or any code that displays or computes recovery rate, diagnosis accuracy, or precision/recall numbers.
---

# Eval Harness Conventions

## Why this skill exists

This project's credibility depends on batch-level honesty, per Razorpay's own stated evaluation bar ("show measured money recovered across a batch... one cherry-picked match proves nothing" — paraphrased across their track descriptions). Code in this area is held to a stricter bar than the rest of the app: it must be structurally incapable of producing a misleading number, not just unlikely to.

## Required structure

1. **`backend/eval/run_batch.py`** is the single entrypoint. It must:
   - Load the full synthetic dataset (all 300-500 records, no default subset)
   - Run every record through the LangGraph agent
   - Run every record through the naive baseline comparator, on the same records
   - Never skip or silently drop a record on error — catch exceptions per-record, log them, and count them as a distinct "errored" category in the final report, not omit them from the denominator

2. **Ground truth isolation.** `true_root_cause`, `recoverable`, and `amount_recoverable_if_acted_correctly` must be stripped from the record before it's passed into the agent graph, and only reattached in the scoring step in `backend/eval/metrics.py`. Structure this as two distinct data shapes if helpful — e.g. `FailureRecordInput` (what the agent sees) vs `FailureRecordWithGroundTruth` (what the evaluator sees) — so it's a type-level guarantee, not just a convention someone could accidentally violate.

3. **`backend/eval/metrics.py` must compute, at minimum, every metric listed in PRD Section 10.2** — precision/recall per class, self-consistency rate, confidence calibration bins, ₹ recovered (system and baseline), unnecessary retries avoided, false diagnoses by class, % correctly stopped, and policy override count. None of these are optional extras; a report missing any of them is incomplete.

4. **Determinism for reproducibility.** Batch eval runs should be re-runnable and produce comparable results run-to-run (low LLM temperature is already set per stack-conventions rule — don't override it here). If a run's results are being compared over time (e.g., before/after a prompt change), save each run's full output to a timestamped file in `backend/eval/runs/`, don't just overwrite the last one.

5. **The frontend Metrics page must read from a saved eval report artifact**, not recompute metrics live on every page load. Wire it to the JSON/CSV output of the most recent `run_batch.py` run.

## Anti-patterns to catch in review

- A "quick test" script that runs on 10 records and gets accidentally left as the thing powering a dashboard number.
- Any function that takes a `limit` or `sample_size` parameter defaulting to something other than the full dataset, used anywhere in the reporting path.
- Metrics computed inline in a notebook or one-off script that never gets consolidated into `metrics.py` — if it's a number that ends up in the pitch, it needs to live in versioned, re-runnable code.
