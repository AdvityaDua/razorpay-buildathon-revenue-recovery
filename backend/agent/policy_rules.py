"""
Deterministic policy / compliance layer.

Sits between the Recovery Agent's LLM output and execution. Pure code (no LLM),
can only narrow or block the LLM's chosen action — never expand it.

The LLM proposes; validate_action() disposes.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.data.schema import (
    AllowedAction,
    Diagnosis,
    FailureRecordInput,
    ProposedAction,
)

logger = logging.getLogger(__name__)

_override_log: list[dict] = []


def get_override_log() -> list[dict]:
    """Return override events since last clear."""
    return list(_override_log)


def clear_override_log() -> None:
    """Clear the override log (call at start of each batch run)."""
    _override_log.clear()


def validate_action(
    diagnosis: Diagnosis,
    proposed_action: ProposedAction,
    context: FailureRecordInput,
) -> AllowedAction:
    """
    Validate and potentially override the LLM's proposed recovery action.

    Applies 9 hard rules in priority order (first match wins). Hard-stop
    conditions short-circuit regardless of what the LLM proposed.
    """

    # Rule 1: mandate revoked OR customer_cancelled → hard STOP
    if context.mandate_status.value == "revoked" or diagnosis.root_cause == "customer_cancelled":
        return _make_stop(
            proposed_action,
            rule="mandate_revoked_or_customer_cancelled",
            reasoning="Hard STOP: mandate is revoked or customer cancelled. "
                      "No retry or notification permitted.",
        )

    # Rule 2: mandate paused → hard STOP this cycle
    if context.mandate_status.value == "paused":
        return _make_stop(
            proposed_action,
            rule="mandate_paused",
            reasoning="Hard STOP: mandate is paused. No action this cycle.",
        )

    # Rule 3: ambiguous diagnosis → hold for review
    if diagnosis.root_cause == "ambiguous":
        return _make_hold(
            proposed_action,
            rule="ambiguous_diagnosis",
            reasoning="Diagnosis is ambiguous. No automated action; flagged for review.",
        )

    # Rule 4: confidence < 0.5 → treat as ambiguous
    if diagnosis.confidence < 0.5:
        return _make_hold(
            proposed_action,
            rule="low_confidence",
            reasoning=f"Confidence {diagnosis.confidence:.2f} < 0.5. "
                      f"Treated as ambiguous regardless of root_cause '{diagnosis.root_cause}'.",
        )

    # Rule 5: retry_attempt >= 3 → hard STOP (halt after exhaustion)
    if context.retry_attempt_number >= 3:
        return _make_stop(
            proposed_action,
            rule="max_retries_exhausted",
            reasoning=f"Retry attempt {context.retry_attempt_number} >= 3. "
                      f"Hard STOP — halt after exhaustion.",
        )

    # Rule 6: amount > ₹15,000 AND not afa_required → restrict to re-auth only
    if context.amount > 15000 and diagnosis.root_cause != "afa_required":
        if proposed_action.action not in ("send_reauth_link", "send_stepup_auth", "stop", "hold_for_review"):
            return _make_override(
                proposed_action,
                allowed_action="send_stepup_auth",
                rule="high_amount_requires_auth",
                reasoning=f"Amount ₹{context.amount} > ₹15,000 and diagnosis is not afa_required. "
                          f"Action restricted to re-auth/step-up only.",
            )

    # Rule 7: mandate_expired → re-auth link only (retry blocked)
    if diagnosis.root_cause == "mandate_expired":
        if proposed_action.action != "send_reauth_link":
            return _make_override(
                proposed_action,
                allowed_action="send_reauth_link",
                rule="mandate_expired_reauth_only",
                reasoning="Mandate expired. Only re-authorization link allowed; retry is blocked.",
            )

    # Rule 8: insufficient_funds + confident → retry with clamped timing (1-5 days)
    if diagnosis.root_cause == "insufficient_funds" and diagnosis.confidence >= 0.5:
        if proposed_action.action == "retry":
            delay = proposed_action.retry_delay_days
            if delay is None:
                delay = 2
            delay = max(1, min(5, delay))
            return AllowedAction(
                action="retry",
                reasoning=proposed_action.reasoning,
                retry_delay_days=delay,
                was_overridden=delay != proposed_action.retry_delay_days,
                override_rule="retry_timing_bounds" if delay != proposed_action.retry_delay_days else None,
                original_proposed_action=proposed_action.action if delay != proposed_action.retry_delay_days else None,
            )

    # Rule 9: genuine_decline → alternate payment prompt only
    if diagnosis.root_cause == "genuine_decline":
        if proposed_action.action != "send_alternate_payment_prompt":
            return _make_override(
                proposed_action,
                allowed_action="send_alternate_payment_prompt",
                rule="genuine_decline_alt_payment_only",
                reasoning="Genuine decline. Only alternate payment method prompt allowed; no blind retry.",
            )

    # No rule triggered: allow as-is
    return AllowedAction(
        action=proposed_action.action,
        reasoning=proposed_action.reasoning,
        retry_delay_days=proposed_action.retry_delay_days,
        was_overridden=False,
    )


def should_skip_recovery_agent(
    diagnosis: Diagnosis,
    context: FailureRecordInput,
) -> tuple[bool, Optional[str]]:
    """
    Check if the policy layer should skip the Recovery Agent entirely.
    Returns (should_skip, reason).
    """
    if context.mandate_status.value == "revoked" or diagnosis.root_cause == "customer_cancelled":
        return True, "Hard STOP: mandate revoked or customer cancelled"
    if context.mandate_status.value == "paused":
        return True, "Hard STOP: mandate paused"
    if diagnosis.root_cause == "ambiguous":
        return True, "Ambiguous diagnosis: no automated action"
    if diagnosis.confidence < 0.5:
        return True, f"Low confidence ({diagnosis.confidence:.2f}): treated as ambiguous"
    if context.retry_attempt_number >= 3:
        return True, "Max retries exhausted (>= 3)"

    return False, None


# ── Helpers ──

def _make_stop(proposed: ProposedAction, rule: str, reasoning: str) -> AllowedAction:
    """Create a STOP action, logging override if proposed was different."""
    was_overridden = proposed.action != "stop"
    action = AllowedAction(
        action="stop",
        reasoning=reasoning,
        was_overridden=was_overridden,
        override_rule=rule if was_overridden else None,
        original_proposed_action=proposed.action if was_overridden else None,
    )
    if was_overridden:
        _log_override(proposed, action, rule)
    return action


def _make_hold(proposed: ProposedAction, rule: str, reasoning: str) -> AllowedAction:
    """Create a HOLD_FOR_REVIEW action, logging override if proposed was different."""
    was_overridden = proposed.action != "hold_for_review"
    action = AllowedAction(
        action="hold_for_review",
        reasoning=reasoning,
        was_overridden=was_overridden,
        override_rule=rule if was_overridden else None,
        original_proposed_action=proposed.action if was_overridden else None,
    )
    if was_overridden:
        _log_override(proposed, action, rule)
    return action


def _make_override(
    proposed: ProposedAction,
    allowed_action: str,
    rule: str,
    reasoning: str,
) -> AllowedAction:
    """Create an overridden action, logging the event."""
    action = AllowedAction(
        action=allowed_action,
        reasoning=reasoning,
        was_overridden=True,
        override_rule=rule,
        original_proposed_action=proposed.action,
    )
    _log_override(proposed, action, rule)
    return action


def _log_override(proposed: ProposedAction, allowed: AllowedAction, rule: str) -> None:
    """Log an override event for metric reporting."""
    event = {
        "original_proposed_action": proposed.action,
        "allowed_action": allowed.action,
        "rule_triggered": rule,
        "original_reasoning": proposed.reasoning,
        "override_reasoning": allowed.reasoning,
    }
    _override_log.append(event)
    logger.info(
        f"Policy override: {proposed.action} → {allowed.action} "
        f"(rule: {rule})"
    )
