"""
Deterministic policy / compliance layer (PRD §7).

This layer sits BETWEEN the Recovery Policy Agent's LLM output and actual
execution. It is pure code (no LLM), and it can only narrow or block the
LLM's chosen action — never expand it.

Design principle: the LLM proposes an action + reasoning; the pure-function
validate_action() is what actually authorizes execution. If proposed_action
violates a hard rule, validate_action substitutes the safe fallback and logs
the override event explicitly.

See: policy-layer-guard skill for implementation rules.
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


# ──────────────────────────────────────────────
# Override tracking — for metric reporting (PRD §10.2)
# ──────────────────────────────────────────────

_override_log: list[dict] = []


def get_override_log() -> list[dict]:
    """Return the list of override events since last clear."""
    return list(_override_log)


def clear_override_log() -> None:
    """Clear the override log (call at start of each batch run)."""
    _override_log.clear()


# ──────────────────────────────────────────────
# Core function: validate_action()
# Pure function, no LLM, no network, fully unit-testable.
# ──────────────────────────────────────────────

def validate_action(
    diagnosis: Diagnosis,
    proposed_action: ProposedAction,
    context: FailureRecordInput,
) -> AllowedAction:
    """
    Validate and potentially override the LLM's proposed recovery action.

    Applies the PRD §7 rule table in priority order (first match wins).
    Hard-stop conditions are checked BEFORE any LLM-proposed action is
    considered — if triggered, they short-circuit regardless of what the
    LLM proposed.

    Returns:
        AllowedAction — may differ from proposed_action if a rule overrode it.
    """

    # ── Rule 1 (PRD §7, row 1): mandate_status == revoked OR diagnosis == customer_cancelled
    # Hard STOP. No retry, no notification. Log and exit.
    # Overridable by LLM: NEVER
    if context.mandate_status.value == "revoked" or diagnosis.root_cause == "customer_cancelled":
        return _make_stop(
            proposed_action,
            rule="mandate_revoked_or_customer_cancelled",
            reasoning="Hard STOP: mandate is revoked or customer cancelled. "
                      "No retry or notification permitted (PRD §7 row 1).",
        )

    # ── Rule 2 (PRD §7, row 2): mandate_status == paused
    # Hard STOP for this cycle. May re-check next cycle.
    # Overridable by LLM: NEVER
    if context.mandate_status.value == "paused":
        return _make_stop(
            proposed_action,
            rule="mandate_paused",
            reasoning="Hard STOP: mandate is paused. No action this cycle (PRD §7 row 2).",
        )

    # ── Rule 3 (PRD §7, row 3): diagnosis == ambiguous
    # No automated recovery action. Flag for review (simulated).
    # Overridable by LLM: NEVER
    if diagnosis.root_cause == "ambiguous":
        return _make_hold(
            proposed_action,
            rule="ambiguous_diagnosis",
            reasoning="Diagnosis is ambiguous. No automated action; flagged for review (PRD §7 row 3).",
        )

    # ── Rule 4 (PRD §7, row 4): confidence < 0.5
    # Treat as ambiguous regardless of stated root_cause.
    # Overridable by LLM: NEVER
    if diagnosis.confidence < 0.5:
        return _make_hold(
            proposed_action,
            rule="low_confidence",
            reasoning=f"Confidence {diagnosis.confidence:.2f} < 0.5. "
                      f"Treated as ambiguous regardless of root_cause '{diagnosis.root_cause}' (PRD §7 row 4).",
        )

    # ── Rule 5 (PRD §7, row 5): retry_attempt_number >= 3
    # Hard STOP — do not retry again this cycle.
    # Overridable by LLM: NEVER
    if context.retry_attempt_number >= 3:
        return _make_stop(
            proposed_action,
            rule="max_retries_exhausted",
            reasoning=f"Retry attempt {context.retry_attempt_number} >= 3. "
                      f"Hard STOP — halt after exhaustion (PRD §7 row 5).",
        )

    # ── Rule 6 (PRD §7, row 6): amount > 15000 AND diagnosis != afa_required
    # Action restricted to re-auth/step-up flow only, not blind retry.
    # Overridable by LLM: NEVER
    if context.amount > 15000 and diagnosis.root_cause != "afa_required":
        if proposed_action.action not in ("send_reauth_link", "send_stepup_auth", "stop", "hold_for_review"):
            return _make_override(
                proposed_action,
                allowed_action="send_stepup_auth",
                rule="high_amount_requires_auth",
                reasoning=f"Amount ₹{context.amount} > ₹15,000 and diagnosis is not afa_required. "
                          f"Action restricted to re-auth/step-up only (PRD §7 row 6).",
            )

    # ── Rule 7 (PRD §7, row 7): diagnosis == mandate_expired
    # Action restricted to re-authorization link only. Retry blocked.
    # Overridable by LLM: NEVER
    if diagnosis.root_cause == "mandate_expired":
        if proposed_action.action != "send_reauth_link":
            return _make_override(
                proposed_action,
                allowed_action="send_reauth_link",
                rule="mandate_expired_reauth_only",
                reasoning="Mandate expired. Action restricted to re-authorization link only; "
                          "retry is blocked (PRD §7 row 7).",
            )

    # ── Rule 8 (PRD §7, row 8): diagnosis == insufficient_funds, confidence >= 0.5
    # LLM may choose retry timing within policy-allowed window (1–5 days).
    # Overridable: timing only, within bounds.
    if diagnosis.root_cause == "insufficient_funds" and diagnosis.confidence >= 0.5:
        if proposed_action.action == "retry":
            # Clamp retry delay to allowed window
            delay = proposed_action.retry_delay_days
            if delay is None:
                delay = 2  # default
            delay = max(1, min(5, delay))
            return AllowedAction(
                action="retry",
                reasoning=proposed_action.reasoning,
                retry_delay_days=delay,
                was_overridden=delay != proposed_action.retry_delay_days,
                override_rule="retry_timing_bounds" if delay != proposed_action.retry_delay_days else None,
                original_proposed_action=proposed_action.action if delay != proposed_action.retry_delay_days else None,
            )

    # ── Rule 9 (PRD §7, row 9): diagnosis == genuine_decline
    # Action restricted to alternate-payment-method prompt, no blind retry.
    # Overridable by LLM: NEVER
    if diagnosis.root_cause == "genuine_decline":
        if proposed_action.action != "send_alternate_payment_prompt":
            return _make_override(
                proposed_action,
                allowed_action="send_alternate_payment_prompt",
                rule="genuine_decline_alt_payment_only",
                reasoning="Genuine decline. Action restricted to alternate payment method prompt; "
                          "no blind retry (PRD §7 row 9).",
            )

    # ── No rule triggered: allow the proposed action as-is
    return AllowedAction(
        action=proposed_action.action,
        reasoning=proposed_action.reasoning,
        retry_delay_days=proposed_action.retry_delay_days,
        was_overridden=False,
    )


# ──────────────────────────────────────────────
# Pre-LLM policy gate (check BEFORE invoking Recovery Agent)
# This handles the cases where we know no action should be taken
# and we can skip the LLM call entirely.
# ──────────────────────────────────────────────

def should_skip_recovery_agent(
    diagnosis: Diagnosis,
    context: FailureRecordInput,
) -> tuple[bool, Optional[str]]:
    """
    Check if the policy layer should skip the Recovery Agent entirely.

    Returns:
        (should_skip, reason) — if should_skip is True, no LLM call needed.
    """
    # Hard STOPs
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


# ──────────────────────────────────────────────
# Helper functions for building AllowedAction responses
# ──────────────────────────────────────────────

def _make_stop(
    proposed: ProposedAction,
    rule: str,
    reasoning: str,
) -> AllowedAction:
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


def _make_hold(
    proposed: ProposedAction,
    rule: str,
    reasoning: str,
) -> AllowedAction:
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


def _log_override(
    proposed: ProposedAction,
    allowed: AllowedAction,
    rule: str,
) -> None:
    """Log an override event for metric reporting (PRD §10.2)."""
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
