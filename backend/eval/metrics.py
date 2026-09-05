"""
Metrics computation — all PRD §10.2 metrics.

Every metric listed is mandatory (eval-harness-conventions skill):
- Diagnosis precision/recall (per root-cause class)
- Self-consistency rate
- Confidence calibration bins
- ₹ recovered (system and baseline)
- Unnecessary retries avoided
- False diagnoses by class
- % correctly stopped
- Policy override count

All computed on the full batch — never on a cherry-picked subset
(AGENTS.md non-negotiable rule 4).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from backend.agent.policy_rules import get_override_log
from backend.data.schema import AuditTrailEntry, FailureRecord


def compute_metrics(
    audit_entries: list[AuditTrailEntry],
    records: list[FailureRecord],
    baseline_results: list[dict],
) -> dict[str, Any]:
    """
    Compute all PRD §10.2 metrics on the full batch.

    Args:
        audit_entries: Agent audit trail entries (one per record)
        records: Full failure records with ground truth
        baseline_results: Baseline results (one per record)

    Returns:
        Complete metrics report dict
    """
    n_total = len(records)
    assert n_total == len(audit_entries), (
        f"Audit entries ({len(audit_entries)}) must match records ({n_total})"
    )
    assert n_total == len(baseline_results), (
        f"Baseline results ({len(baseline_results)}) must match records ({n_total})"
    )

    # Build lookup for easy access
    record_by_id = {r.mandate_id: r for r in records}

    # ── 1. Diagnosis precision/recall per class ──
    precision_recall = _compute_precision_recall(audit_entries, records)

    # ── 2. Self-consistency rate ──
    self_consistency = _compute_self_consistency(audit_entries)

    # ── 3. Confidence calibration ──
    calibration = _compute_confidence_calibration(audit_entries, records)

    # ── 4. ₹ recovered (system) ──
    system_recovered = sum(e.amount_recovered for e in audit_entries)

    # ── 5. ₹ recovered (baseline) ──
    baseline_recovered = sum(b["amount_recovered"] for b in baseline_results)

    # ── 6. Unnecessary retries avoided ──
    unnecessary_retries_avoided = _compute_unnecessary_retries_avoided(
        audit_entries, records, baseline_results
    )

    # ── 7. False diagnoses by class ──
    false_diagnoses = _compute_false_diagnoses(audit_entries, records)

    # ── 8. % correctly stopped ──
    correctly_stopped_pct = _compute_correctly_stopped(audit_entries, records)

    # ── 9. Policy override count ──
    override_log = get_override_log()
    policy_override_count = len(override_log)

    # ── 10. Additional useful stats ──
    n_errors = sum(1 for e in audit_entries if e.diagnosis_error is not None)
    n_held = sum(1 for e in audit_entries if e.was_held)

    # Recovery rate comparison
    total_recoverable = sum(
        r.amount_recoverable_if_acted_correctly
        for r in records
        if r.recoverable
    )

    return {
        "batch_size": n_total,
        "diagnosis_precision_recall": precision_recall,
        "self_consistency_rate": self_consistency,
        "confidence_calibration": calibration,
        "system_recovered_inr": round(system_recovered, 2),
        "baseline_recovered_inr": round(baseline_recovered, 2),
        "total_recoverable_inr": round(total_recoverable, 2),
        "system_recovery_rate_pct": round(
            (system_recovered / total_recoverable * 100) if total_recoverable > 0 else 0, 2
        ),
        "baseline_recovery_rate_pct": round(
            (baseline_recovered / total_recoverable * 100) if total_recoverable > 0 else 0, 2
        ),
        "unnecessary_retries_avoided": unnecessary_retries_avoided,
        "false_diagnoses": false_diagnoses,
        "correctly_stopped_pct": correctly_stopped_pct,
        "policy_override_count": policy_override_count,
        "policy_override_details": override_log,
        "n_errors": n_errors,
        "n_held": n_held,
    }


def _compute_precision_recall(
    entries: list[AuditTrailEntry],
    records: list[FailureRecord],
) -> dict[str, dict[str, float]]:
    """Compute precision and recall per root-cause class."""
    record_by_id = {r.mandate_id: r for r in records}

    classes = [
        "insufficient_funds", "mandate_expired", "afa_required",
        "customer_cancelled", "genuine_decline", "ambiguous",
    ]

    # Count TP, FP, FN per class
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)

    for entry in entries:
        record = record_by_id.get(entry.mandate_id)
        if record is None or entry.diagnosis is None:
            continue

        predicted = entry.diagnosis.root_cause
        actual = record.true_root_cause

        if predicted == actual:
            tp[actual] += 1
        else:
            fp[predicted] += 1
            fn[actual] += 1

    result = {}
    for cls in classes:
        precision = tp[cls] / (tp[cls] + fp[cls]) if (tp[cls] + fp[cls]) > 0 else 0.0
        recall = tp[cls] / (tp[cls] + fn[cls]) if (tp[cls] + fn[cls]) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        result[cls] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "true_positives": tp[cls],
            "false_positives": fp[cls],
            "false_negatives": fn[cls],
        }

    # Overall accuracy
    total_correct = sum(tp.values())
    total = sum(1 for e in entries if e.diagnosis is not None)
    result["overall"] = {
        "accuracy": round(total_correct / total, 4) if total > 0 else 0.0,
        "total_evaluated": total,
        "total_correct": total_correct,
    }

    return result


def _compute_self_consistency(entries: list[AuditTrailEntry]) -> dict[str, Any]:
    """
    Compute self-consistency rate — % of records where root_cause
    is a valid member of 'plausible' causes (PRD §10.2).
    """
    consistent = 0
    inconsistent = 0
    evaluated = 0

    for entry in entries:
        if entry.diagnosis is None:
            continue
        evaluated += 1

        if entry.diagnosis.root_cause == "ambiguous":
            consistent += 1
            continue

        plausible = {
            ce.cause for ce in entry.diagnosis.cause_evaluations
            if ce.verdict == "plausible"
        }

        if entry.diagnosis.root_cause in plausible:
            consistent += 1
        else:
            inconsistent += 1

    return {
        "rate": round(consistent / evaluated, 4) if evaluated > 0 else 0.0,
        "consistent": consistent,
        "inconsistent": inconsistent,
        "total_evaluated": evaluated,
    }


def _compute_confidence_calibration(
    entries: list[AuditTrailEntry],
    records: list[FailureRecord],
) -> list[dict[str, Any]]:
    """
    Compute confidence calibration — binned confidence vs actual accuracy.

    Bins: [0.0-0.2), [0.2-0.4), [0.4-0.6), [0.6-0.8), [0.8-1.0]
    """
    record_by_id = {r.mandate_id: r for r in records}

    bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    bin_correct: dict[tuple, int] = defaultdict(int)
    bin_total: dict[tuple, int] = defaultdict(int)
    bin_confidence_sum: dict[tuple, float] = defaultdict(float)

    for entry in entries:
        if entry.diagnosis is None:
            continue

        record = record_by_id.get(entry.mandate_id)
        if record is None:
            continue

        conf = entry.diagnosis.confidence
        is_correct = entry.diagnosis.root_cause == record.true_root_cause

        for lo, hi in bins:
            if lo <= conf < hi:
                bin_total[(lo, hi)] += 1
                bin_confidence_sum[(lo, hi)] += conf
                if is_correct:
                    bin_correct[(lo, hi)] += 1
                break

    result = []
    for lo, hi in bins:
        n = bin_total[(lo, hi)]
        result.append({
            "bin": f"{lo:.1f}-{min(hi, 1.0):.1f}",
            "count": n,
            "accuracy": round(bin_correct[(lo, hi)] / n, 4) if n > 0 else 0.0,
            "avg_confidence": round(bin_confidence_sum[(lo, hi)] / n, 4) if n > 0 else 0.0,
        })

    return result


def _compute_unnecessary_retries_avoided(
    entries: list[AuditTrailEntry],
    records: list[FailureRecord],
    baseline_results: list[dict],
) -> dict[str, int]:
    """
    Count customer_cancelled / hard-stop cases where system correctly
    took no action vs. baseline retrying anyway.
    """
    record_by_id = {r.mandate_id: r for r in records}
    baseline_by_id = {b["mandate_id"]: b for b in baseline_results}

    avoided = 0
    baseline_unnecessary = 0

    for entry in entries:
        record = record_by_id.get(entry.mandate_id)
        baseline = baseline_by_id.get(entry.mandate_id)
        if record is None or baseline is None:
            continue

        # Hard-stop cases: customer_cancelled, mandate revoked/paused
        is_hard_stop = record.true_root_cause in ("customer_cancelled",) or not record.recoverable

        if is_hard_stop:
            # Did baseline retry anyway?
            if "retry" in baseline.get("action_taken", ""):
                baseline_unnecessary += 1

                # Did our system correctly stop?
                if entry.allowed_action and entry.allowed_action.action in ("stop", "hold_for_review"):
                    avoided += 1

    return {
        "system_correctly_stopped": avoided,
        "baseline_unnecessary_retries": baseline_unnecessary,
    }


def _compute_false_diagnoses(
    entries: list[AuditTrailEntry],
    records: list[FailureRecord],
) -> dict[str, Any]:
    """Count where root_cause ≠ true_root_cause, broken down by class."""
    record_by_id = {r.mandate_id: r for r in records}

    false_by_class: dict[str, int] = defaultdict(int)
    total_false = 0

    for entry in entries:
        if entry.diagnosis is None:
            continue

        record = record_by_id.get(entry.mandate_id)
        if record is None:
            continue

        if entry.diagnosis.root_cause != record.true_root_cause:
            false_by_class[record.true_root_cause] += 1
            total_false += 1

    return {
        "total_false": total_false,
        "by_true_class": dict(false_by_class),
    }


def _compute_correctly_stopped(
    entries: list[AuditTrailEntry],
    records: list[FailureRecord],
) -> dict[str, Any]:
    """
    Of all true hard-stop cases, % where system correctly produced STOP.

    True hard-stop cases: customer_cancelled, plus any non-recoverable case.
    """
    record_by_id = {r.mandate_id: r for r in records}

    total_hard_stop = 0
    correctly_stopped = 0

    for entry in entries:
        record = record_by_id.get(entry.mandate_id)
        if record is None:
            continue

        # True hard-stop: customer_cancelled or non-recoverable
        is_hard_stop = (
            record.true_root_cause == "customer_cancelled"
            or not record.recoverable
        )

        if is_hard_stop:
            total_hard_stop += 1
            if entry.allowed_action and entry.allowed_action.action in ("stop", "hold_for_review"):
                correctly_stopped += 1

    return {
        "correctly_stopped": correctly_stopped,
        "total_hard_stop_cases": total_hard_stop,
        "percentage": round(
            correctly_stopped / total_hard_stop * 100, 2
        ) if total_hard_stop > 0 else 0.0,
    }
