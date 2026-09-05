"""
Pydantic models for the AI Revenue Recovery Orchestrator.

Implements:
- FailureRecord (PRD §6.1) — full record with ground truth
- FailureRecordInput — what the agent sees (ground truth stripped)
- CauseEvaluation, Diagnosis (PRD §9) — structured agent output
- RecoveryAction, AllowedAction — recovery policy output
- AuditTrailEntry — per-record audit log
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class MandateType(str, Enum):
    upi_autopay = "upi_autopay"
    nach = "nach"
    card_emandate = "card_emandate"


class MandateStatus(str, Enum):
    active = "active"
    paused = "paused"
    revoked = "revoked"
    expired = "expired"


ROOT_CAUSE_TYPES = Literal[
    "insufficient_funds",
    "mandate_expired",
    "afa_required",
    "customer_cancelled",
    "genuine_decline",
    "ambiguous",
]

NON_AMBIGUOUS_CAUSES = Literal[
    "insufficient_funds",
    "mandate_expired",
    "afa_required",
    "customer_cancelled",
    "genuine_decline",
]

RECOVERY_ACTION_TYPES = Literal[
    "retry",
    "send_reminder",
    "send_reauth_link",
    "send_stepup_auth",
    "send_alternate_payment_prompt",
    "hold_for_review",
    "stop",
]


# ──────────────────────────────────────────────
# Failure Record (PRD §6.1)
# ──────────────────────────────────────────────

class FailureRecordBase(BaseModel):
    """Fields visible to the agent — no ground truth."""
    mandate_id: str
    customer_id: str
    merchant_id: str
    amount: float = Field(description="Amount in INR")
    mandate_type: MandateType
    scheduled_debit_at: datetime
    actual_attempt_at: datetime
    pre_debit_notification_sent_at: Optional[datetime] = None

    # Error fields — realistically null ~30-40% of the time (PRD §12.1)
    error_code: Optional[str] = None
    error_reason: Optional[str] = None
    error_source: Optional[str] = None
    error_step: Optional[str] = None

    # Mandate info
    mandate_status: MandateStatus
    mandate_created_at: datetime
    mandate_validity_days: int

    # Customer history
    customer_prior_successful_payments: int
    customer_prior_failures: int
    customer_last_payment_date: Optional[date] = None
    retry_attempt_number: int


class FailureRecordInput(FailureRecordBase):
    """What the agent sees — ground truth stripped per eval-harness-conventions."""
    pass


class FailureRecord(FailureRecordBase):
    """Full record including ground truth — used by evaluator only."""
    true_root_cause: ROOT_CAUSE_TYPES
    recoverable: bool
    true_recovery_action: Optional[str] = None
    amount_recoverable_if_acted_correctly: float


# ──────────────────────────────────────────────
# Diagnosis Agent Output (PRD §9)
# ──────────────────────────────────────────────

class CauseEvaluation(BaseModel):
    """Per-cause assessment. All 5 non-ambiguous causes must be evaluated."""
    cause: NON_AMBIGUOUS_CAUSES
    verdict: Literal["ruled_out", "plausible"]
    reason: str = Field(description="Must cite specific input field(s)")


class Diagnosis(BaseModel):
    """Structured diagnosis output from the Diagnosis Agent."""
    cause_evaluations: list[CauseEvaluation] = Field(
        description="All 5 non-ambiguous causes, each evaluated"
    )
    root_cause: ROOT_CAUSE_TYPES
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(
        description="Must cite specific field names/values, not generic restatement"
    )


# ──────────────────────────────────────────────
# Recovery Action
# ──────────────────────────────────────────────

class ProposedAction(BaseModel):
    """What the Recovery Policy Agent LLM proposes."""
    action: RECOVERY_ACTION_TYPES
    reasoning: str
    retry_delay_days: Optional[int] = Field(
        default=None,
        description="For retry actions: delay in days (1-5 allowed by policy)"
    )


class AllowedAction(BaseModel):
    """What validate_action() actually authorizes — may differ from proposal."""
    action: RECOVERY_ACTION_TYPES
    reasoning: str
    retry_delay_days: Optional[int] = None
    was_overridden: bool = False
    override_rule: Optional[str] = None
    original_proposed_action: Optional[RECOVERY_ACTION_TYPES] = None


# ──────────────────────────────────────────────
# Audit Trail (PRD §5, non-negotiable rule 5)
# ──────────────────────────────────────────────

class AuditTrailEntry(BaseModel):
    """Full audit trail entry per record — evidence → diagnosis → action → outcome."""
    mandate_id: str
    customer_id: str
    amount: float

    # Diagnosis stage
    diagnosis: Optional[Diagnosis] = None
    diagnosis_error: Optional[str] = None

    # Policy check
    policy_check_passed: bool = False
    policy_stop_reason: Optional[str] = None

    # Action
    proposed_action: Optional[ProposedAction] = None
    allowed_action: Optional[AllowedAction] = None

    # Outcome (simulated)
    simulated_outcome: Optional[str] = None
    amount_recovered: float = 0.0

    # Meta
    was_held: bool = False
    hold_reason: Optional[str] = None


# ──────────────────────────────────────────────
# Agent Graph State
# ──────────────────────────────────────────────

class AgentState(BaseModel):
    """State object passed through the LangGraph nodes."""
    record: FailureRecordInput
    ground_truth: Optional[FailureRecord] = None  # only attached in eval
    diagnosis: Optional[Diagnosis] = None
    diagnosis_error: Optional[str] = None
    proposed_action: Optional[ProposedAction] = None
    allowed_action: Optional[AllowedAction] = None
    policy_stop_reason: Optional[str] = None
    simulated_outcome: Optional[str] = None
    amount_recovered: float = 0.0
    was_held: bool = False
    hold_reason: Optional[str] = None
    audit_entry: Optional[AuditTrailEntry] = None
