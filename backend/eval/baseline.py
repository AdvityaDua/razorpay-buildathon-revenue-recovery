"""
Naive fixed-schedule retry baseline.

Mirrors standard gateway default behavior:
- Retry next day, halt after 3 attempts
- No diagnosis, no differentiation by cause
"""

from __future__ import annotations

from backend.data.schema import FailureRecord


def run_baseline(record: FailureRecord) -> dict:
    """Run naive baseline on a single record. Returns dict for metrics computation."""

    # Halt after 3 attempts
    if record.retry_attempt_number >= 3:
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "stop_exhausted",
            "simulated_outcome": _resolve_stop(record),
            "amount_recovered": 0.0,
        }

    # Baseline retries blindly — doesn't check mandate status
    if record.recoverable and record.true_root_cause == "insufficient_funds":
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "retry_next_day",
            "simulated_outcome": "recovered",
            "amount_recovered": record.amount_recoverable_if_acted_correctly,
        }
    elif record.recoverable and record.true_root_cause in ("afa_required", "genuine_decline"):
        # Blind retry fails for cases needing specific action
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "retry_next_day",
            "simulated_outcome": "failed_retry",
            "amount_recovered": 0.0,
        }
    elif record.true_root_cause == "mandate_expired":
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "retry_next_day",
            "simulated_outcome": "failed_retry",
            "amount_recovered": 0.0,
        }
    elif record.true_root_cause == "customer_cancelled":
        # Baseline retries cancelled mandates — compliance violation
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "retry_next_day",
            "simulated_outcome": "unnecessary_retry_on_cancelled",
            "amount_recovered": 0.0,
        }
    elif record.true_root_cause == "ambiguous":
        if record.recoverable:
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
        return {
            "mandate_id": record.mandate_id,
            "action_taken": "retry_next_day",
            "simulated_outcome": "failed_retry",
            "amount_recovered": 0.0,
        }


def _resolve_stop(record: FailureRecord) -> str:
    if not record.recoverable:
        return "correctly_stopped"
    return "missed_recovery"


def run_baseline_batch(records: list[FailureRecord]) -> list[dict]:
    """Run baseline on a full batch. No records skipped."""
    return [run_baseline(r) for r in records]
