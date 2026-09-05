"""
Naive fixed-schedule retry baseline (PRD §10.1).

Mirrors Razorpay's documented default behavior:
- Retry next day
- Shift for holidays (not modeled — simplified for synthetic data)
- Halt after exhaustion (retry_attempt_number >= 3)
- No diagnosis, no differentiation by cause

This is what the agent is compared against.
"""

from __future__ import annotations

from backend.data.schema import FailureRecord


def run_baseline(record: FailureRecord) -> dict:
    """
    Run naive baseline on a single record.

    Returns a dict matching the shape needed by metrics computation:
    - action_taken: what the baseline would do
    - simulated_outcome: result against ground truth
    - amount_recovered: ₹ recovered by baseline
    """

    # Halt after exhaustion — Razorpay stops retrying after 3 attempts
    if record.retry_attempt_number >= 3:
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "stop_exhausted",
            "simulated_outcome": _resolve_stop(record),
            "amount_recovered": 0.0,
        }

    # Baseline doesn't check mandate status — it just retries blindly
    # (This is a key differentiator: the agent correctly stops on revoked/cancelled)
    if record.recoverable and record.true_root_cause == "insufficient_funds":
        # Naive retry succeeds for insufficient_funds (most common recoverable case)
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "retry_next_day",
            "simulated_outcome": "recovered",
            "amount_recovered": record.amount_recoverable_if_acted_correctly,
        }
    elif record.recoverable and record.true_root_cause in ("afa_required", "genuine_decline"):
        # Blind retry fails for cases needing specific action (re-auth, alt payment)
        # The baseline doesn't know what action to take — it just retries
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "retry_next_day",
            "simulated_outcome": "failed_retry",
            "amount_recovered": 0.0,
        }
    elif record.true_root_cause == "mandate_expired":
        # Retry on expired mandate fails — needs re-authorization
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "retry_next_day",
            "simulated_outcome": "failed_retry",
            "amount_recovered": 0.0,
        }
    elif record.true_root_cause == "customer_cancelled":
        # Baseline retries even on cancelled mandates — compliance violation
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "retry_next_day",
            "simulated_outcome": "unnecessary_retry_on_cancelled",
            "amount_recovered": 0.0,
        }
    elif record.true_root_cause == "ambiguous":
        # Baseline retries ambiguous cases blindly
        if record.recoverable:
            # Lucky — might work
            return {
                "mandate_id": record.mandate_id,
                "action_taken": "retry_next_day",
                "simulated_outcome": "recovered",
                "amount_recovered": record.amount_recoverable_if_acted_correctly,
            }
        else:
            return {
                "mandate_id": record.mandate_id,
                "action_taken": "retry_next_day",
                "simulated_outcome": "failed_retry",
                "amount_recovered": 0.0,
            }
    else:
        # Fallback
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "retry_next_day",
            "simulated_outcome": "failed_retry",
            "amount_recovered": 0.0,
        }


def _resolve_stop(record: FailureRecord) -> str:
    """Determine outcome when baseline stops (exhausted retries)."""
    if not record.recoverable:
        return "correctly_stopped"
    else:
        return "missed_recovery"


def run_baseline_batch(records: list[FailureRecord]) -> list[dict]:
    """Run baseline on a full batch. No records skipped (eval-harness-conventions)."""
    return [run_baseline(r) for r in records]
