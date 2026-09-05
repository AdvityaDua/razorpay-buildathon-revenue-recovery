"""
LangGraph graph definition — full agent pipeline.

Graph structure (PRD §8.2):
    failure_event
         ↓
    Diagnosis Node — LLM call, structured output
         ↓
    Confidence Gate — pure code: confidence < 0.5 or ambiguous → HOLD
         ↓                                                        ↓
    Policy Gate    — pure code: checks hard-stop conditions    HOLD (logged)
         ↓
    Recovery Policy Agent — LLM proposes action + timing
         ↓
    validate_action() — pure code, final hard gate
         ↓
    Simulated Execution — resolves outcome against ground truth
         ↓
    Audit Log — writes full trail entry
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from backend.agent.diagnosis_node import run_diagnosis
from backend.agent.policy_rules import (
    should_skip_recovery_agent,
    validate_action,
)
from backend.agent.recovery_node import run_recovery_agent
from backend.data.schema import (
    AllowedAction,
    AuditTrailEntry,
    Diagnosis,
    FailureRecord,
    FailureRecordInput,
    ProposedAction,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Graph State
# ──────────────────────────────────────────────

class GraphState(TypedDict, total=False):
    """State passed through the LangGraph nodes."""
    record: FailureRecordInput
    ground_truth: FailureRecord | None
    diagnosis: Diagnosis | None
    diagnosis_error: str | None
    proposed_action: ProposedAction | None
    allowed_action: AllowedAction | None
    policy_stop_reason: str | None
    simulated_outcome: str | None
    amount_recovered: float
    was_held: bool
    hold_reason: str | None
    audit_entry: AuditTrailEntry | None


# ──────────────────────────────────────────────
# Node functions
# ──────────────────────────────────────────────

async def diagnosis_node(state: GraphState) -> GraphState:
    """Stage 1: Run the Diagnosis Agent."""
    record = state["record"]

    try:
        diagnosis = await run_diagnosis(record)
        state["diagnosis"] = diagnosis
        state["diagnosis_error"] = None
        logger.info(
            f"Diagnosis: {diagnosis.root_cause} (confidence={diagnosis.confidence:.2f}) "
            f"for {record.mandate_id}"
        )
    except Exception as e:
        logger.error(f"Diagnosis failed for {record.mandate_id}: {e}")
        state["diagnosis"] = None
        state["diagnosis_error"] = str(e)

    return state


async def confidence_gate_node(state: GraphState) -> GraphState:
    """
    Pure-code gate: route low-confidence / ambiguous diagnoses to HOLD.

    This runs before any recovery LLM call to save compute on cases
    where the policy layer would block action anyway.
    """
    diagnosis = state.get("diagnosis")

    if diagnosis is None:
        state["was_held"] = True
        state["hold_reason"] = f"Diagnosis failed: {state.get('diagnosis_error', 'unknown')}"
        return state

    record = state["record"]
    should_skip, reason = should_skip_recovery_agent(diagnosis, record)

    if should_skip:
        state["was_held"] = True
        state["hold_reason"] = reason

        # For hard-stop cases, create an appropriate allowed_action
        if "Hard STOP" in (reason or ""):
            state["allowed_action"] = AllowedAction(
                action="stop",
                reasoning=reason or "Policy hard stop",
                was_overridden=False,
            )
            state["policy_stop_reason"] = reason
        else:
            state["allowed_action"] = AllowedAction(
                action="hold_for_review",
                reasoning=reason or "Held for review",
                was_overridden=False,
            )

        logger.info(f"Confidence gate: HOLD for {record.mandate_id} — {reason}")
    else:
        state["was_held"] = False

    return state


async def recovery_agent_node(state: GraphState) -> GraphState:
    """Stage 2: Run the Recovery Policy Agent (LLM proposes action)."""
    if state.get("was_held"):
        return state  # Skip — already routed to HOLD

    record = state["record"]
    diagnosis = state["diagnosis"]

    proposed = await run_recovery_agent(record, diagnosis)
    state["proposed_action"] = proposed

    logger.info(
        f"Recovery proposal: {proposed.action} for {record.mandate_id} "
        f"(diagnosis={diagnosis.root_cause})"
    )

    return state


async def validate_action_node(state: GraphState) -> GraphState:
    """
    Pure-code final gate: validate_action() — can override LLM proposal.

    This is THE critical security boundary (policy-layer-guard skill).
    The proposed_action NEVER flows directly into execution.
    """
    if state.get("was_held"):
        return state  # Already handled

    diagnosis = state["diagnosis"]
    proposed = state["proposed_action"]
    record = state["record"]

    allowed = validate_action(diagnosis, proposed, record)
    state["allowed_action"] = allowed

    if allowed.was_overridden:
        logger.warning(
            f"Policy override for {record.mandate_id}: "
            f"{proposed.action} → {allowed.action} "
            f"(rule: {allowed.override_rule})"
        )
    else:
        logger.info(
            f"Policy approved: {allowed.action} for {record.mandate_id}"
        )

    return state


async def simulated_execution_node(state: GraphState) -> GraphState:
    """
    Simulate action execution — resolve outcome against ground truth.

    No real payments/messages sent (PRD §4.1). Outcome determined by:
    - Whether the action matches the ground truth's true_recovery_action
    - Whether the case is actually recoverable
    """
    allowed = state.get("allowed_action")
    ground_truth = state.get("ground_truth")

    if allowed is None:
        state["simulated_outcome"] = "no_action"
        state["amount_recovered"] = 0.0
        return state

    if ground_truth is None:
        # No ground truth available (e.g., live/non-eval mode)
        state["simulated_outcome"] = "simulated_success"
        state["amount_recovered"] = 0.0
        return state

    # Determine outcome
    if allowed.action == "stop":
        if not ground_truth.recoverable:
            state["simulated_outcome"] = "correctly_stopped"
            state["amount_recovered"] = 0.0
        else:
            state["simulated_outcome"] = "missed_recovery"
            state["amount_recovered"] = 0.0

    elif allowed.action == "hold_for_review":
        state["simulated_outcome"] = "held_for_review"
        state["amount_recovered"] = 0.0

    elif ground_truth.recoverable:
        # Check if the action is correct
        if allowed.action == ground_truth.true_recovery_action:
            state["simulated_outcome"] = "recovered"
            state["amount_recovered"] = ground_truth.amount_recoverable_if_acted_correctly
        else:
            # Wrong action but case was recoverable — partial credit
            # (e.g., sent reminder instead of retry — less effective but not zero)
            state["simulated_outcome"] = "partial_recovery"
            state["amount_recovered"] = ground_truth.amount_recoverable_if_acted_correctly * 0.3

    else:
        # Case not recoverable but we tried anyway
        state["simulated_outcome"] = "unnecessary_action"
        state["amount_recovered"] = 0.0

    logger.info(
        f"Simulated execution for {state['record'].mandate_id}: "
        f"{state['simulated_outcome']} (₹{state['amount_recovered']:,.2f})"
    )

    return state


async def audit_log_node(state: GraphState) -> GraphState:
    """Write full audit trail entry per record (PRD non-negotiable rule 5)."""
    record = state["record"]

    entry = AuditTrailEntry(
        mandate_id=record.mandate_id,
        customer_id=record.customer_id,
        amount=record.amount,
        diagnosis=state.get("diagnosis"),
        diagnosis_error=state.get("diagnosis_error"),
        policy_check_passed=not state.get("was_held", False),
        policy_stop_reason=state.get("policy_stop_reason"),
        proposed_action=state.get("proposed_action"),
        allowed_action=state.get("allowed_action"),
        simulated_outcome=state.get("simulated_outcome"),
        amount_recovered=state.get("amount_recovered", 0.0),
        was_held=state.get("was_held", False),
        hold_reason=state.get("hold_reason"),
    )

    state["audit_entry"] = entry

    logger.info(
        f"Audit logged: {record.mandate_id} | "
        f"diagnosis={entry.diagnosis.root_cause if entry.diagnosis else 'error'} | "
        f"action={entry.allowed_action.action if entry.allowed_action else 'none'} | "
        f"outcome={entry.simulated_outcome}"
    )

    return state


# ──────────────────────────────────────────────
# Graph construction
# ──────────────────────────────────────────────

async def run_agent_pipeline(
    record: FailureRecordInput,
    ground_truth: FailureRecord | None = None,
) -> GraphState:
    """
    Run the full agent pipeline on a single failure record.

    Uses sequential execution (no LangGraph StateGraph needed for MVP —
    the node structure is the same, just called sequentially).
    This keeps the dependency graph simple while preserving the
    node-level audit trail structure from PRD §8.2.

    Args:
        record: Failure record (ground truth stripped)
        ground_truth: Full record with ground truth (for eval only)

    Returns:
        Final graph state with audit trail entry
    """
    state: GraphState = {
        "record": record,
        "ground_truth": ground_truth,
        "diagnosis": None,
        "diagnosis_error": None,
        "proposed_action": None,
        "allowed_action": None,
        "policy_stop_reason": None,
        "simulated_outcome": None,
        "amount_recovered": 0.0,
        "was_held": False,
        "hold_reason": None,
        "audit_entry": None,
    }

    # Execute nodes sequentially per PRD §8.2 graph structure
    state = await diagnosis_node(state)
    state = await confidence_gate_node(state)
    state = await recovery_agent_node(state)
    state = await validate_action_node(state)
    state = await simulated_execution_node(state)
    state = await audit_log_node(state)

    return state
