"""
Batch evaluation runner — single entrypoint (eval-harness-conventions).

Must:
- Load the FULL synthetic dataset (all records, no default subset)
- Run every record through the LangGraph agent
- Run every record through the naive baseline
- Never skip/drop a record on error — catch, log, count in report
- Save timestamped output to backend/eval/runs/

Per eval-harness-conventions: ground truth (true_root_cause, recoverable,
amount_recoverable_if_acted_correctly) is stripped before passing to agent,
only reattached in scoring step.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from backend.agent.graph import run_agent_pipeline
from backend.agent.policy_rules import clear_override_log
from backend.data.generate_synthetic import generate_dataset, load_dataset, save_dataset
from backend.data.schema import (
    AuditTrailEntry,
    FailureRecord,
    FailureRecordInput,
)
from backend.eval.baseline import run_baseline_batch
from backend.eval.metrics import compute_metrics

logger = logging.getLogger(__name__)


def _strip_ground_truth(record: FailureRecord) -> FailureRecordInput:
    """
    Strip ground truth fields to create agent-visible input.

    This is the type-level guarantee required by eval-harness-conventions:
    FailureRecordInput vs FailureRecord ensures the agent never sees ground truth.
    """
    return FailureRecordInput(
        mandate_id=record.mandate_id,
        customer_id=record.customer_id,
        merchant_id=record.merchant_id,
        amount=record.amount,
        mandate_type=record.mandate_type,
        scheduled_debit_at=record.scheduled_debit_at,
        actual_attempt_at=record.actual_attempt_at,
        pre_debit_notification_sent_at=record.pre_debit_notification_sent_at,
        error_code=record.error_code,
        error_reason=record.error_reason,
        error_source=record.error_source,
        error_step=record.error_step,
        mandate_status=record.mandate_status,
        mandate_created_at=record.mandate_created_at,
        mandate_validity_days=record.mandate_validity_days,
        customer_prior_successful_payments=record.customer_prior_successful_payments,
        customer_prior_failures=record.customer_prior_failures,
        customer_last_payment_date=record.customer_last_payment_date,
        retry_attempt_number=record.retry_attempt_number,
    )


async def run_batch(
    dataset_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict:
    """
    Run full batch evaluation.

    1. Load ALL records from dataset
    2. Run each through agent pipeline (with error handling per record)
    3. Run each through baseline
    4. Compute metrics
    5. Save timestamped report

    Returns:
        Complete metrics report dict
    """
    # Setup
    if output_dir is None:
        output_dir = Path(__file__).parent / "runs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clear override log for fresh batch
    clear_override_log()

    # ── Load dataset (full, no subset) ──
    if dataset_path and dataset_path.exists():
        records = load_dataset(dataset_path)
    else:
        # Generate if not exists
        default_path = Path(__file__).parent.parent / "data" / "dataset.json"
        if default_path.exists():
            records = load_dataset(default_path)
        else:
            logger.info("No dataset found, generating...")
            records = generate_dataset(n_records=400, seed=42)
            save_dataset(records, default_path)

    n_total = len(records)
    logger.info(f"Loaded {n_total} records for batch evaluation")

    # ── Run agent on every record ──
    audit_entries: list[AuditTrailEntry] = []
    errors: list[dict] = []

    for i, record in enumerate(records):
        try:
            # Strip ground truth (eval-harness-conventions: type-level guarantee)
            agent_input = _strip_ground_truth(record)

            # Run full pipeline
            state = await run_agent_pipeline(agent_input, ground_truth=record)

            if state.get("audit_entry"):
                audit_entries.append(state["audit_entry"])
            else:
                # Create minimal audit entry for errored records
                audit_entries.append(AuditTrailEntry(
                    mandate_id=record.mandate_id,
                    customer_id=record.customer_id,
                    amount=record.amount,
                    diagnosis_error="No audit entry produced",
                ))

            if (i + 1) % 50 == 0:
                logger.info(f"Progress: {i + 1}/{n_total} records processed")

        except Exception as e:
            # Never skip/drop — count as errored (eval-harness-conventions rule 1)
            logger.error(f"Record {i} ({record.mandate_id}) failed: {e}")
            errors.append({
                "index": i,
                "mandate_id": record.mandate_id,
                "error": str(e),
            })
            audit_entries.append(AuditTrailEntry(
                mandate_id=record.mandate_id,
                customer_id=record.customer_id,
                amount=record.amount,
                diagnosis_error=str(e),
            ))

    logger.info(f"Agent pipeline complete: {n_total - len(errors)} succeeded, {len(errors)} errored")

    # ── Run baseline on every record ──
    baseline_results = run_baseline_batch(records)

    # ── Compute metrics ──
    metrics = compute_metrics(audit_entries, records, baseline_results)
    metrics["errors"] = errors

    # ── Save timestamped report ──
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"batch_report_{timestamp}.json"

    # Build full report with audit entries
    full_report = {
        "metadata": {
            "timestamp": timestamp,
            "batch_size": n_total,
            "n_errors": len(errors),
            "dataset_path": str(dataset_path or "default"),
        },
        "metrics": metrics,
        "audit_entries": [e.model_dump(mode="json") for e in audit_entries],
        "baseline_results": baseline_results,
    }

    with open(report_path, "w") as f:
        json.dump(full_report, f, indent=2, default=str)

    # Also save as "latest" for easy frontend access
    latest_path = output_dir / "latest_report.json"
    with open(latest_path, "w") as f:
        json.dump(full_report, f, indent=2, default=str)

    logger.info(f"Report saved to {report_path}")

    # ── Console summary ──
    _print_summary(metrics, n_total)

    return full_report


def _print_summary(metrics: dict, n_total: int) -> None:
    """Print summary to console."""
    print("\n" + "=" * 60)
    print("  BATCH EVALUATION REPORT")
    print("=" * 60)
    print(f"\n  Batch size: {n_total}")
    print(f"  Errors: {metrics['n_errors']}")
    print(f"  Held for review: {metrics['n_held']}")

    print(f"\n  ₹ Recovered (System):   ₹{metrics['system_recovered_inr']:>12,.2f}")
    print(f"  ₹ Recovered (Baseline): ₹{metrics['baseline_recovered_inr']:>12,.2f}")
    print(f"  Total Recoverable:      ₹{metrics['total_recoverable_inr']:>12,.2f}")

    print(f"\n  System Recovery Rate:   {metrics['system_recovery_rate_pct']:.1f}%")
    print(f"  Baseline Recovery Rate: {metrics['baseline_recovery_rate_pct']:.1f}%")

    cs = metrics["correctly_stopped_pct"]
    print(f"\n  Correctly Stopped: {cs['correctly_stopped']}/{cs['total_hard_stop_cases']} ({cs['percentage']:.1f}%)")

    ur = metrics["unnecessary_retries_avoided"]
    print(f"  Unnecessary Retries Avoided: {ur['system_correctly_stopped']} (baseline had {ur['baseline_unnecessary_retries']})")

    print(f"\n  Policy Override Count: {metrics['policy_override_count']}")

    sc = metrics["self_consistency_rate"]
    print(f"  Self-Consistency Rate: {sc['rate']:.1%} ({sc['consistent']}/{sc['total_evaluated']})")

    print(f"\n  Diagnosis Accuracy: {metrics['diagnosis_precision_recall'].get('overall', {}).get('accuracy', 0):.1%}")

    print(f"\n  False Diagnoses: {metrics['false_diagnoses']['total_false']}")
    for cls, count in sorted(metrics['false_diagnoses'].get('by_true_class', {}).items()):
        print(f"    {cls}: {count}")

    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
    asyncio.run(run_batch())
