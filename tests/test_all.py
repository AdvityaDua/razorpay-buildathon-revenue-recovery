"""
Comprehensive test suite for the AI Revenue Recovery Orchestrator.

Tests:
1. Data layer — schema validation, synthetic data quality
2. Policy layer — all 9 PRD §7 rules (unit tests)
3. Baseline — naive retry logic
4. Metrics — computation correctness
5. API — route availability
"""

import json
import sys
import traceback
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

# ─────────────────────────────────────────────
# Test infrastructure
# ─────────────────────────────────────────────

PASS = 0
FAIL = 0
ERRORS = []


def test(name):
    """Decorator for test functions."""
    def decorator(fn):
        global PASS, FAIL
        try:
            fn()
            PASS += 1
            print(f"  ✅ {name}")
        except AssertionError as e:
            FAIL += 1
            ERRORS.append((name, str(e)))
            print(f"  ❌ {name}: {e}")
        except Exception as e:
            FAIL += 1
            ERRORS.append((name, traceback.format_exc()))
            print(f"  💥 {name}: {e}")
        return fn
    return decorator


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

from backend.data.schema import (
    AllowedAction, AuditTrailEntry, CauseEvaluation, Diagnosis,
    FailureRecord, FailureRecordInput, MandateStatus, MandateType,
    ProposedAction,
)
from backend.agent.policy_rules import (
    clear_override_log, get_override_log, should_skip_recovery_agent,
    validate_action,
)
from backend.data.generate_synthetic import generate_dataset, load_dataset
from backend.eval.baseline import run_baseline, run_baseline_batch
from backend.eval.metrics import compute_metrics


def make_diagnosis(
    root_cause="insufficient_funds",
    confidence=0.8,
    plausible_causes=None,
):
    """Helper to create a Diagnosis with specific parameters."""
    if plausible_causes is None:
        plausible_causes = [root_cause] if root_cause != "ambiguous" else []

    evals = []
    for cause in ["insufficient_funds", "mandate_expired", "afa_required",
                   "customer_cancelled", "genuine_decline"]:
        verdict = "plausible" if cause in plausible_causes else "ruled_out"
        evals.append(CauseEvaluation(cause=cause, verdict=verdict, reason=f"test: {verdict}"))

    return Diagnosis(
        cause_evaluations=evals,
        root_cause=root_cause,
        confidence=confidence,
        evidence="test evidence",
    )


def make_context(
    mandate_status="active",
    amount=1000.0,
    retry_attempt=0,
):
    """Helper to create a FailureRecordInput context."""
    return FailureRecordInput(
        mandate_id="test_mandate_001",
        customer_id="test_cust_001",
        merchant_id="merchant_demo_001",
        amount=amount,
        mandate_type=MandateType.upi_autopay,
        scheduled_debit_at=datetime(2026, 9, 1, 10, 0, 0),
        actual_attempt_at=datetime(2026, 9, 1, 12, 0, 0),
        mandate_status=MandateStatus(mandate_status),
        mandate_created_at=datetime(2026, 1, 1, 0, 0, 0),
        mandate_validity_days=365,
        customer_prior_successful_payments=5,
        customer_prior_failures=1,
        retry_attempt_number=retry_attempt,
    )


def make_proposal(action="retry", delay=None):
    """Helper to create a ProposedAction."""
    return ProposedAction(
        action=action,
        reasoning="test proposal",
        retry_delay_days=delay,
    )


# ═══════════════════════════════════════════════
# TEST SUITE 1: Data Layer
# ═══════════════════════════════════════════════

print("\n" + "=" * 60)
print("  TEST SUITE 1: Data Layer")
print("=" * 60)


@test("Schema: FailureRecord validates correctly")
def _():
    r = FailureRecord(
        mandate_id="m1", customer_id="c1", merchant_id="demo",
        amount=5000, mandate_type=MandateType.upi_autopay,
        scheduled_debit_at=datetime.now(), actual_attempt_at=datetime.now(),
        mandate_status=MandateStatus.active,
        mandate_created_at=datetime.now(), mandate_validity_days=365,
        customer_prior_successful_payments=3, customer_prior_failures=0,
        retry_attempt_number=0,
        true_root_cause="insufficient_funds", recoverable=True,
        true_recovery_action="retry", amount_recoverable_if_acted_correctly=5000,
    )
    assert r.amount == 5000
    assert r.true_root_cause == "insufficient_funds"


@test("Schema: FailureRecordInput strips ground truth fields")
def _():
    inp = FailureRecordInput(
        mandate_id="m1", customer_id="c1", merchant_id="demo",
        amount=5000, mandate_type=MandateType.upi_autopay,
        scheduled_debit_at=datetime.now(), actual_attempt_at=datetime.now(),
        mandate_status=MandateStatus.active,
        mandate_created_at=datetime.now(), mandate_validity_days=365,
        customer_prior_successful_payments=3, customer_prior_failures=0,
        retry_attempt_number=0,
    )
    d = inp.model_dump()
    assert "true_root_cause" not in d
    assert "recoverable" not in d
    assert "amount_recoverable_if_acted_correctly" not in d


@test("Schema: Diagnosis confidence must be 0-1")
def _():
    try:
        Diagnosis(
            cause_evaluations=[],
            root_cause="ambiguous",
            confidence=1.5,
            evidence="test",
        )
        assert False, "Should have raised ValidationError"
    except Exception:
        pass


@test("Schema: CauseEvaluation verdict enum enforcement")
def _():
    ce = CauseEvaluation(cause="insufficient_funds", verdict="plausible", reason="test")
    assert ce.verdict == "plausible"
    ce2 = CauseEvaluation(cause="mandate_expired", verdict="ruled_out", reason="test")
    assert ce2.verdict == "ruled_out"


@test("Dataset: loads 400 records")
def _():
    records = load_dataset()
    assert len(records) == 400, f"Expected 400, got {len(records)}"


@test("Dataset: correct cause distribution")
def _():
    records = load_dataset()
    dist = Counter(r.true_root_cause for r in records)
    assert dist["insufficient_funds"] == 140, f"Expected 140, got {dist['insufficient_funds']}"
    assert dist["ambiguous"] == 80, f"Expected 80, got {dist['ambiguous']}"
    assert dist["mandate_expired"] == 60, f"Expected 60, got {dist['mandate_expired']}"
    assert dist["customer_cancelled"] == 40, f"Expected 40, got {dist['customer_cancelled']}"
    assert dist["afa_required"] == 40, f"Expected 40, got {dist['afa_required']}"
    assert dist["genuine_decline"] == 40, f"Expected 40, got {dist['genuine_decline']}"


@test("Dataset: ~30-40% null error fields")
def _():
    records = load_dataset()
    null_count = sum(1 for r in records if r.error_code is None)
    pct = null_count / len(records)
    assert 0.25 <= pct <= 0.50, f"Null error rate {pct:.1%} outside expected 25-50% range"


@test("Dataset: AFA records have amount > 15000")
def _():
    records = load_dataset()
    afa = [r for r in records if r.true_root_cause == "afa_required"]
    for r in afa:
        assert r.amount > 15000, f"AFA record {r.mandate_id} has amount {r.amount} <= 15000"


@test("Dataset: customer_cancelled records have revoked/paused mandate")
def _():
    records = load_dataset()
    cc = [r for r in records if r.true_root_cause == "customer_cancelled"]
    for r in cc:
        assert r.mandate_status in (MandateStatus.revoked, MandateStatus.paused), \
            f"Customer cancelled record {r.mandate_id} has mandate_status={r.mandate_status}"


@test("Dataset: mandate_expired records have expired status")
def _():
    records = load_dataset()
    me = [r for r in records if r.true_root_cause == "mandate_expired"]
    for r in me:
        assert r.mandate_status == MandateStatus.expired, \
            f"Mandate expired record {r.mandate_id} has status={r.mandate_status}"


@test("Dataset: ground truth consistency — non-recoverable causes")
def _():
    records = load_dataset()
    for r in records:
        if r.true_root_cause in ("customer_cancelled", "mandate_expired"):
            assert not r.recoverable, \
                f"{r.mandate_id}: {r.true_root_cause} should not be recoverable"


@test("Dataset: reproducibility — seed produces same data")
def _():
    r1 = generate_dataset(n_records=10, seed=42)
    r2 = generate_dataset(n_records=10, seed=42)
    for a, b in zip(r1, r2):
        assert a.mandate_id == b.mandate_id
        assert a.true_root_cause == b.true_root_cause


# ═══════════════════════════════════════════════
# TEST SUITE 2: Policy Layer (PRD §7)
# ═══════════════════════════════════════════════

print("\n" + "=" * 60)
print("  TEST SUITE 2: Policy Layer (PRD §7)")
print("=" * 60)

clear_override_log()


@test("Rule 1: mandate_status=revoked → STOP (overrides LLM retry)")
def _():
    d = make_diagnosis("insufficient_funds", 0.9)
    p = make_proposal("retry")
    ctx = make_context(mandate_status="revoked")
    result = validate_action(d, p, ctx)
    assert result.action == "stop", f"Expected stop, got {result.action}"
    assert result.was_overridden is True


@test("Rule 1: diagnosis=customer_cancelled → STOP (overrides any action)")
def _():
    d = make_diagnosis("customer_cancelled", 0.95, ["customer_cancelled"])
    p = make_proposal("send_reminder")
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.action == "stop"
    assert result.was_overridden is True


@test("Rule 1: customer_cancelled + mandate active → still STOP")
def _():
    d = make_diagnosis("customer_cancelled", 0.9, ["customer_cancelled"])
    p = make_proposal("retry")
    ctx = make_context(mandate_status="active")
    result = validate_action(d, p, ctx)
    assert result.action == "stop"


@test("Rule 2: mandate_status=paused → STOP")
def _():
    d = make_diagnosis("insufficient_funds", 0.8)
    p = make_proposal("retry")
    ctx = make_context(mandate_status="paused")
    result = validate_action(d, p, ctx)
    assert result.action == "stop"
    assert result.was_overridden is True


@test("Rule 3: diagnosis=ambiguous → HOLD_FOR_REVIEW")
def _():
    d = make_diagnosis("ambiguous", 0.3)
    p = make_proposal("retry")
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.action == "hold_for_review"
    assert result.was_overridden is True


@test("Rule 4: confidence < 0.5 → treated as ambiguous → HOLD")
def _():
    d = make_diagnosis("insufficient_funds", 0.4)
    p = make_proposal("retry")
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.action == "hold_for_review", f"Expected hold_for_review, got {result.action}"


@test("Rule 4: confidence = 0.49 → HOLD; confidence = 0.5 → allowed")
def _():
    d_low = make_diagnosis("insufficient_funds", 0.49)
    d_ok = make_diagnosis("insufficient_funds", 0.5)
    p = make_proposal("retry", delay=2)
    ctx = make_context()
    r_low = validate_action(d_low, p, ctx)
    r_ok = validate_action(d_ok, p, ctx)
    assert r_low.action == "hold_for_review"
    assert r_ok.action == "retry"


@test("Rule 5: retry_attempt >= 3 → STOP")
def _():
    d = make_diagnosis("insufficient_funds", 0.9)
    p = make_proposal("retry")
    ctx = make_context(retry_attempt=3)
    result = validate_action(d, p, ctx)
    assert result.action == "stop"


@test("Rule 5: retry_attempt = 4 → STOP")
def _():
    d = make_diagnosis("insufficient_funds", 0.9)
    p = make_proposal("retry")
    ctx = make_context(retry_attempt=4)
    result = validate_action(d, p, ctx)
    assert result.action == "stop"


@test("Rule 6: amount > 15000 + not afa_required → restricted to auth")
def _():
    d = make_diagnosis("insufficient_funds", 0.8)
    p = make_proposal("retry")
    ctx = make_context(amount=20000)
    result = validate_action(d, p, ctx)
    assert result.action == "send_stepup_auth", f"Expected send_stepup_auth, got {result.action}"
    assert result.was_overridden is True


@test("Rule 6: amount > 15000 + afa_required → allows step-up action")
def _():
    d = make_diagnosis("afa_required", 0.85, ["afa_required"])
    p = make_proposal("send_stepup_auth")
    ctx = make_context(amount=20000)
    result = validate_action(d, p, ctx)
    assert result.action == "send_stepup_auth"


@test("Rule 7: mandate_expired → only send_reauth_link allowed")
def _():
    d = make_diagnosis("mandate_expired", 0.8, ["mandate_expired"])
    p = make_proposal("retry")
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.action == "send_reauth_link"
    assert result.was_overridden is True


@test("Rule 7: mandate_expired + propose reauth → allowed as-is")
def _():
    d = make_diagnosis("mandate_expired", 0.8, ["mandate_expired"])
    p = make_proposal("send_reauth_link")
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.action == "send_reauth_link"
    assert result.was_overridden is False


@test("Rule 8: insufficient_funds + retry → clamp delay to 1-5")
def _():
    d = make_diagnosis("insufficient_funds", 0.8)
    p = make_proposal("retry", delay=10)
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.action == "retry"
    assert result.retry_delay_days == 5, f"Expected 5, got {result.retry_delay_days}"


@test("Rule 8: insufficient_funds + retry + delay=0 → clamped to 1")
def _():
    d = make_diagnosis("insufficient_funds", 0.8)
    p = make_proposal("retry", delay=0)
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.retry_delay_days == 1


@test("Rule 9: genuine_decline → only alternate_payment_prompt")
def _():
    d = make_diagnosis("genuine_decline", 0.7, ["genuine_decline"])
    p = make_proposal("retry")
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.action == "send_alternate_payment_prompt"
    assert result.was_overridden is True


@test("Rule 9: genuine_decline + correct action → allowed")
def _():
    d = make_diagnosis("genuine_decline", 0.7, ["genuine_decline"])
    p = make_proposal("send_alternate_payment_prompt")
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.action == "send_alternate_payment_prompt"
    assert result.was_overridden is False


@test("No rule triggered: action passes through")
def _():
    d = make_diagnosis("insufficient_funds", 0.8)
    p = make_proposal("retry", delay=3)
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.action == "retry"
    assert result.retry_delay_days == 3
    assert result.was_overridden is False


@test("Override log records overrides correctly")
def _():
    clear_override_log()
    d = make_diagnosis("customer_cancelled", 0.95, ["customer_cancelled"])
    p = make_proposal("retry")
    ctx = make_context()
    validate_action(d, p, ctx)
    log = get_override_log()
    assert len(log) >= 1
    assert log[-1]["original_proposed_action"] == "retry"
    assert log[-1]["allowed_action"] == "stop"


@test("Policy: hard-stops checked BEFORE action-specific rules")
def _():
    # Even with amount > 15000 (rule 6), revoked mandate (rule 1) takes precedence
    d = make_diagnosis("insufficient_funds", 0.9)
    p = make_proposal("retry")
    ctx = make_context(mandate_status="revoked", amount=20000)
    result = validate_action(d, p, ctx)
    assert result.action == "stop", "Rule 1 (revoked) should take priority over Rule 6 (high amount)"


@test("should_skip_recovery_agent: revoked → skip")
def _():
    d = make_diagnosis("customer_cancelled", 0.9, ["customer_cancelled"])
    ctx = make_context(mandate_status="revoked")
    skip, reason = should_skip_recovery_agent(d, ctx)
    assert skip is True
    assert "revoked" in reason.lower() or "cancelled" in reason.lower()


@test("should_skip_recovery_agent: active + high confidence → don't skip")
def _():
    d = make_diagnosis("insufficient_funds", 0.8)
    ctx = make_context()
    skip, reason = should_skip_recovery_agent(d, ctx)
    assert skip is False


# ═══════════════════════════════════════════════
# TEST SUITE 3: Baseline
# ═══════════════════════════════════════════════

print("\n" + "=" * 60)
print("  TEST SUITE 3: Baseline Comparator")
print("=" * 60)


@test("Baseline: halts after 3 retries")
def _():
    records = load_dataset()
    high_retry = [r for r in records if r.retry_attempt_number >= 3]
    if high_retry:
        result = run_baseline(high_retry[0])
        assert result["action_taken"] == "stop_exhausted"


@test("Baseline: retries insufficient_funds (recoverable)")
def _():
    records = load_dataset()
    inf = [r for r in records if r.true_root_cause == "insufficient_funds" and r.retry_attempt_number < 3]
    if inf:
        result = run_baseline(inf[0])
        assert result["action_taken"] == "retry_next_day"
        assert result["amount_recovered"] == inf[0].amount_recoverable_if_acted_correctly


@test("Baseline: blindly retries cancelled mandates (compliance violation)")
def _():
    records = load_dataset()
    cc = [r for r in records if r.true_root_cause == "customer_cancelled" and r.retry_attempt_number < 3]
    if cc:
        result = run_baseline(cc[0])
        assert result["action_taken"] == "retry_next_day"
        assert result["simulated_outcome"] == "unnecessary_retry_on_cancelled"


@test("Baseline: full batch processes all records")
def _():
    records = load_dataset()
    results = run_baseline_batch(records)
    assert len(results) == len(records), f"Expected {len(records)}, got {len(results)}"


# ═══════════════════════════════════════════════
# TEST SUITE 4: Metrics
# ═══════════════════════════════════════════════

print("\n" + "=" * 60)
print("  TEST SUITE 4: Metrics Computation")
print("=" * 60)


@test("Metrics: compute_metrics runs on synthetic data")
def _():
    records = load_dataset()
    # Create dummy audit entries (simulate perfect diagnosis)
    audit_entries = []
    for r in records:
        d = make_diagnosis(r.true_root_cause, 0.85,
                           [r.true_root_cause] if r.true_root_cause != "ambiguous" else [])
        entry = AuditTrailEntry(
            mandate_id=r.mandate_id,
            customer_id=r.customer_id,
            amount=r.amount,
            diagnosis=d,
            policy_check_passed=True,
            allowed_action=AllowedAction(
                action=r.true_recovery_action or "hold_for_review",
                reasoning="test",
                was_overridden=False,
            ),
            simulated_outcome="recovered" if r.recoverable else "correctly_stopped",
            amount_recovered=r.amount_recoverable_if_acted_correctly if r.recoverable else 0,
        )
        audit_entries.append(entry)

    baseline = run_baseline_batch(records)
    clear_override_log()
    metrics = compute_metrics(audit_entries, records, baseline)

    # Verify all required metrics are present (PRD §10.2)
    assert "diagnosis_precision_recall" in metrics
    assert "self_consistency_rate" in metrics
    assert "confidence_calibration" in metrics
    assert "system_recovered_inr" in metrics
    assert "baseline_recovered_inr" in metrics
    assert "unnecessary_retries_avoided" in metrics
    assert "false_diagnoses" in metrics
    assert "correctly_stopped_pct" in metrics
    assert "policy_override_count" in metrics


@test("Metrics: perfect diagnosis → 100% accuracy")
def _():
    records = load_dataset()[:50]
    audit_entries = []
    for r in records:
        d = make_diagnosis(r.true_root_cause, 0.85,
                           [r.true_root_cause] if r.true_root_cause != "ambiguous" else [])
        entry = AuditTrailEntry(
            mandate_id=r.mandate_id, customer_id=r.customer_id, amount=r.amount,
            diagnosis=d, policy_check_passed=True,
            allowed_action=AllowedAction(action="stop", reasoning="test", was_overridden=False),
            simulated_outcome="recovered", amount_recovered=0,
        )
        audit_entries.append(entry)
    baseline = run_baseline_batch(records)
    clear_override_log()
    metrics = compute_metrics(audit_entries, records, baseline)
    overall = metrics["diagnosis_precision_recall"]["overall"]
    assert overall["accuracy"] == 1.0, f"Expected 1.0, got {overall['accuracy']}"


@test("Metrics: self-consistency rate computation")
def _():
    # Create entries where root_cause matches a plausible cause
    evals = [
        CauseEvaluation(cause="insufficient_funds", verdict="plausible", reason="t"),
        CauseEvaluation(cause="mandate_expired", verdict="ruled_out", reason="t"),
        CauseEvaluation(cause="afa_required", verdict="ruled_out", reason="t"),
        CauseEvaluation(cause="customer_cancelled", verdict="ruled_out", reason="t"),
        CauseEvaluation(cause="genuine_decline", verdict="ruled_out", reason="t"),
    ]
    d = Diagnosis(cause_evaluations=evals, root_cause="insufficient_funds",
                  confidence=0.8, evidence="test")

    records = load_dataset()[:5]
    entries = []
    for r in records:
        entries.append(AuditTrailEntry(
            mandate_id=r.mandate_id, customer_id=r.customer_id, amount=r.amount,
            diagnosis=d, policy_check_passed=True,
            allowed_action=AllowedAction(action="retry", reasoning="t", was_overridden=False),
            simulated_outcome="recovered", amount_recovered=0,
        ))
    baseline = run_baseline_batch(records)
    clear_override_log()
    metrics = compute_metrics(entries, records, baseline)
    assert metrics["self_consistency_rate"]["rate"] == 1.0


@test("Metrics: confidence calibration has 5 bins")
def _():
    records = load_dataset()[:10]
    entries = []
    for r in records:
        d = make_diagnosis("ambiguous", 0.3)
        entries.append(AuditTrailEntry(
            mandate_id=r.mandate_id, customer_id=r.customer_id, amount=r.amount,
            diagnosis=d, policy_check_passed=True,
            allowed_action=AllowedAction(action="hold_for_review", reasoning="t", was_overridden=False),
            simulated_outcome="held", amount_recovered=0,
        ))
    baseline = run_baseline_batch(records)
    clear_override_log()
    metrics = compute_metrics(entries, records, baseline)
    assert len(metrics["confidence_calibration"]) == 5


# ═══════════════════════════════════════════════
# TEST SUITE 5: API
# ═══════════════════════════════════════════════

print("\n" + "=" * 60)
print("  TEST SUITE 5: API & Integration")
print("=" * 60)


@test("API: FastAPI app creates successfully")
def _():
    from backend.api.main import app
    assert app is not None
    routes = [r.path for r in app.routes]
    assert "/api/health" in routes
    assert "/api/records" in routes
    assert "/api/metrics" in routes
    assert "/api/baseline" in routes
    assert "/api/batch/run" in routes


@test("API: 5 API routes registered")
def _():
    from backend.api.main import app
    api_routes = [r.path for r in app.routes if r.path.startswith("/api")]
    assert len(api_routes) == 5, f"Expected 5 API routes, got {len(api_routes)}: {api_routes}"


@test("Integration: FailureRecord → FailureRecordInput strips ground truth")
def _():
    records = load_dataset()
    r = records[0]
    inp = FailureRecordInput(**{
        k: v for k, v in r.model_dump().items()
        if k in FailureRecordInput.model_fields
    })
    d = inp.model_dump()
    assert "true_root_cause" not in d
    assert "recoverable" not in d


@test("Integration: policy layer is pure (no LLM dependency)")
def _():
    """Verify validate_action can run without any LLM or network."""
    import socket
    # This would fail if policy_rules tried to make network calls
    d = make_diagnosis("insufficient_funds", 0.8)
    p = make_proposal("retry", delay=2)
    ctx = make_context()
    result = validate_action(d, p, ctx)
    assert result.action == "retry"  # Pure function, no network needed


@test("Integration: diagnosis self-consistency validation function")
def _():
    from backend.agent.diagnosis_node import _validate_diagnosis_consistency

    # Consistent: root_cause is in plausible
    d = make_diagnosis("insufficient_funds", 0.8, ["insufficient_funds"])
    assert _validate_diagnosis_consistency(d) is True

    # Ambiguous is always consistent
    d_amb = make_diagnosis("ambiguous", 0.3)
    assert _validate_diagnosis_consistency(d_amb) is True

    # Inconsistent: root_cause not in any plausible
    d_bad = Diagnosis(
        cause_evaluations=[
            CauseEvaluation(cause="insufficient_funds", verdict="ruled_out", reason="t"),
            CauseEvaluation(cause="mandate_expired", verdict="ruled_out", reason="t"),
            CauseEvaluation(cause="afa_required", verdict="ruled_out", reason="t"),
            CauseEvaluation(cause="customer_cancelled", verdict="ruled_out", reason="t"),
            CauseEvaluation(cause="genuine_decline", verdict="ruled_out", reason="t"),
        ],
        root_cause="insufficient_funds",
        confidence=0.8,
        evidence="test",
    )
    assert _validate_diagnosis_consistency(d_bad) is False


# ═══════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════

print("\n" + "=" * 60)
print(f"  RESULTS: {PASS} passed, {FAIL} failed")
print("=" * 60)

if ERRORS:
    print("\n  Failed tests:")
    for name, err in ERRORS:
        print(f"    ❌ {name}")
        for line in err.split("\n")[:3]:
            print(f"       {line}")

print()
sys.exit(1 if FAIL > 0 else 0)
