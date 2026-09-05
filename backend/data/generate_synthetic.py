"""
Synthetic failure record generator.

Generates 300-500 labeled failure records with:
- Realistic distribution across 6 root causes (PRD §6.3)
- ~30-40% null error fields (PRD §12.1 — confirmed real Razorpay behavior)
- ~20-30% genuinely ambiguous/noisy cases
- Ground truth baked in at generation time (never derived from agent output)

Distribution anchored loosely on reported Indian autopay/e-mandate failure breakdowns.
"""

import json
import random
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from backend.data.schema import (
    FailureRecord,
    MandateStatus,
    MandateType,
)

# ──────────────────────────────────────────────
# Distribution config (PRD §6.3)
# Loosely anchored on real Indian autopay failure breakdowns:
#   insufficient_funds: ~35% (most common in recurring payments)
#   mandate_expired: ~15%
#   afa_required: ~10% (amount-based auth threshold)
#   customer_cancelled: ~10%
#   genuine_decline: ~10%
#   ambiguous: ~20% (deliberately injected for eval credibility)
# ──────────────────────────────────────────────

CAUSE_DISTRIBUTION = {
    "insufficient_funds": 0.35,
    "mandate_expired": 0.15,
    "afa_required": 0.10,
    "customer_cancelled": 0.10,
    "genuine_decline": 0.10,
    "ambiguous": 0.20,
}

# Error codes/reasons that correspond to each cause (realistic Razorpay-style)
ERROR_SIGNALS = {
    "insufficient_funds": {
        "error_codes": ["INSUFFICIENT_FUNDS", "BAL_INSUFFICIENT", "LOW_BALANCE"],
        "error_reasons": [
            "Customer account has insufficient balance",
            "Transaction declined due to insufficient funds",
            "Balance not sufficient for debit",
        ],
        "error_sources": ["bank", "issuer"],
        "error_steps": ["payment_authorization", "debit"],
    },
    "mandate_expired": {
        "error_codes": ["MANDATE_EXPIRED", "AUTH_EXPIRED", "EMANDATE_LAPSED"],
        "error_reasons": [
            "Mandate has expired",
            "Authorization validity period has lapsed",
            "E-mandate no longer valid",
        ],
        "error_sources": ["gateway", "bank"],
        "error_steps": ["mandate_validation", "payment_authorization"],
    },
    "afa_required": {
        "error_codes": ["AFA_REQUIRED", "STEP_UP_AUTH_NEEDED", "ADDITIONAL_AUTH"],
        "error_reasons": [
            "Additional factor authentication required for this amount",
            "Amount exceeds auto-debit limit, step-up authentication needed",
            "Transaction requires customer authentication",
        ],
        "error_sources": ["gateway", "npci"],
        "error_steps": ["payment_authorization"],
    },
    "customer_cancelled": {
        "error_codes": ["MANDATE_REVOKED", "MANDATE_CANCELLED", "CUSTOMER_REVOKED"],
        "error_reasons": [
            "Customer has revoked the mandate",
            "Mandate cancelled by customer request",
            "Authorization revoked by account holder",
        ],
        "error_sources": ["bank", "customer"],
        "error_steps": ["mandate_validation"],
    },
    "genuine_decline": {
        "error_codes": ["BANK_DECLINE", "NETWORK_ERROR", "TECHNICAL_DECLINE", "GATEWAY_ERROR"],
        "error_reasons": [
            "Transaction declined by issuing bank",
            "Network connectivity error during processing",
            "Technical error at bank end",
            "Payment gateway timeout",
        ],
        "error_sources": ["bank", "gateway", "network"],
        "error_steps": ["payment_authorization", "payment_processing"],
    },
}


def _random_datetime(start: datetime, end: datetime) -> datetime:
    """Generate a random datetime between start and end."""
    delta = end - start
    random_seconds = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=random_seconds)


def _generate_record(
    record_index: int,
    true_cause: str,
    null_error_rate: float = 0.35,
) -> FailureRecord:
    """Generate a single failure record with the given true root cause."""

    mandate_id = f"mandate_{uuid.uuid4().hex[:12]}"
    customer_id = f"cust_{uuid.uuid4().hex[:8]}"
    merchant_id = "merchant_demo_001"  # single demo merchant (PRD §4.2)

    # Amount: realistic subscription range ₹99 – ₹25,000
    if true_cause == "afa_required":
        # AFA cases: amount must be > ₹15,000
        amount = round(random.uniform(15001, 25000), 2)
    else:
        amount = round(random.uniform(99, 20000), 2)

    mandate_type = random.choice(list(MandateType))

    # Timing
    now = datetime(2026, 9, 1, 10, 0, 0)
    scheduled_debit_at = _random_datetime(
        now - timedelta(days=30), now - timedelta(days=1)
    )
    actual_attempt_at = scheduled_debit_at + timedelta(
        hours=random.randint(0, 48)
    )

    # Pre-debit notification (mandatory 24h before under RBI rules)
    if random.random() < 0.7:
        pre_debit_notification_sent_at = scheduled_debit_at - timedelta(
            hours=random.randint(24, 72)
        )
    else:
        # ~30% missing pre-debit notification
        pre_debit_notification_sent_at = None

    # Mandate status — must be consistent with true cause
    if true_cause == "customer_cancelled":
        mandate_status = random.choice([MandateStatus.revoked, MandateStatus.paused])
    elif true_cause == "mandate_expired":
        mandate_status = MandateStatus.expired
    else:
        mandate_status = MandateStatus.active

    mandate_created_at = scheduled_debit_at - timedelta(
        days=random.randint(30, 365)
    )

    # Validity: if expired, set short validity; otherwise normal
    if true_cause == "mandate_expired":
        mandate_validity_days = random.randint(30, 90)
    else:
        mandate_validity_days = random.randint(180, 730)

    # Customer history
    customer_prior_successful_payments = random.randint(0, 24)
    customer_prior_failures = random.randint(0, 5)
    customer_last_payment_date = (
        (scheduled_debit_at - timedelta(days=random.randint(7, 60))).date()
        if customer_prior_successful_payments > 0
        else None
    )
    retry_attempt_number = random.randint(0, 4)

    # Error fields — null out ~30-40% of the time (PRD §6.3, §12.1)
    is_ambiguous = true_cause == "ambiguous"
    should_null_errors = random.random() < null_error_rate

    if is_ambiguous or should_null_errors:
        # Ambiguous cases: either all null, or misleading signals
        if is_ambiguous and random.random() < 0.5:
            # Some ambiguous cases have misleading error fields
            misleading_cause = random.choice(list(ERROR_SIGNALS.keys()))
            signals = ERROR_SIGNALS[misleading_cause]
            error_code = random.choice(signals["error_codes"])
            error_reason = random.choice(signals["error_reasons"])
            error_source = random.choice(signals["error_sources"]) if random.random() < 0.5 else None
            error_step = random.choice(signals["error_steps"]) if random.random() < 0.5 else None
        else:
            error_code = None
            error_reason = None
            error_source = None
            error_step = None
    else:
        # Clear signal for this cause
        signals = ERROR_SIGNALS[true_cause]
        error_code = random.choice(signals["error_codes"])
        error_reason = random.choice(signals["error_reasons"])
        error_source = random.choice(signals["error_sources"])
        error_step = random.choice(signals["error_steps"])

    # Ground truth
    recoverable = true_cause in ("insufficient_funds", "afa_required", "genuine_decline")
    if true_cause == "ambiguous":
        # Ambiguous cases: randomly recoverable
        recoverable = random.random() < 0.3

    true_recovery_action = _get_true_recovery_action(true_cause)
    amount_recoverable = amount if recoverable else 0.0

    return FailureRecord(
        mandate_id=mandate_id,
        customer_id=customer_id,
        merchant_id=merchant_id,
        amount=amount,
        mandate_type=mandate_type,
        scheduled_debit_at=scheduled_debit_at,
        actual_attempt_at=actual_attempt_at,
        pre_debit_notification_sent_at=pre_debit_notification_sent_at,
        error_code=error_code,
        error_reason=error_reason,
        error_source=error_source,
        error_step=error_step,
        mandate_status=mandate_status,
        mandate_created_at=mandate_created_at,
        mandate_validity_days=mandate_validity_days,
        customer_prior_successful_payments=customer_prior_successful_payments,
        customer_prior_failures=customer_prior_failures,
        customer_last_payment_date=customer_last_payment_date,
        retry_attempt_number=retry_attempt_number,
        true_root_cause=true_cause,
        recoverable=recoverable,
        true_recovery_action=true_recovery_action,
        amount_recoverable_if_acted_correctly=amount_recoverable,
    )


def _get_true_recovery_action(cause: str) -> str | None:
    """Map cause to the correct recovery action (ground truth)."""
    mapping = {
        "insufficient_funds": "retry",
        "mandate_expired": "send_reauth_link",
        "afa_required": "send_stepup_auth",
        "customer_cancelled": "stop",
        "genuine_decline": "send_alternate_payment_prompt",
        "ambiguous": "hold_for_review",
    }
    return mapping.get(cause)


def generate_dataset(
    n_records: int = 400,
    seed: int = 42,
) -> list[FailureRecord]:
    """
    Generate a synthetic dataset of failure records.

    Args:
        n_records: Number of records to generate (300-500 per PRD §4.1)
        seed: Random seed for reproducibility
    """
    random.seed(seed)

    records: list[FailureRecord] = []

    # Allocate records per cause based on distribution
    cause_counts: dict[str, int] = {}
    remaining = n_records
    causes = list(CAUSE_DISTRIBUTION.keys())

    for i, cause in enumerate(causes):
        if i == len(causes) - 1:
            count = remaining  # last cause gets the remainder
        else:
            count = round(n_records * CAUSE_DISTRIBUTION[cause])
            remaining -= count
        cause_counts[cause] = count

    # Generate records
    idx = 0
    for cause, count in cause_counts.items():
        for _ in range(count):
            records.append(_generate_record(idx, cause))
            idx += 1

    # Shuffle to avoid ordering bias
    random.shuffle(records)

    return records


def save_dataset(
    records: list[FailureRecord],
    output_path: Path | None = None,
) -> Path:
    """Save dataset to JSON file."""
    if output_path is None:
        output_path = Path(__file__).parent / "dataset.json"

    data = [r.model_dump(mode="json") for r in records]

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Generated {len(records)} records → {output_path}")

    # Print distribution summary
    from collections import Counter
    dist = Counter(r.true_root_cause for r in records)
    null_error_count = sum(1 for r in records if r.error_code is None)

    print(f"\nDistribution:")
    for cause, count in sorted(dist.items()):
        print(f"  {cause}: {count} ({count/len(records)*100:.1f}%)")
    print(f"\nNull error fields: {null_error_count}/{len(records)} ({null_error_count/len(records)*100:.1f}%)")
    print(f"Recoverable: {sum(1 for r in records if r.recoverable)}/{len(records)}")

    return output_path


def load_dataset(path: Path | None = None) -> list[FailureRecord]:
    """Load dataset from JSON file."""
    if path is None:
        path = Path(__file__).parent / "dataset.json"

    with open(path) as f:
        data = json.load(f)

    return [FailureRecord.model_validate(r) for r in data]


if __name__ == "__main__":
    records = generate_dataset(n_records=400, seed=42)
    save_dataset(records)
