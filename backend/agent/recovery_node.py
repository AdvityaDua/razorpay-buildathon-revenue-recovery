"""
Recovery Policy Agent — Stage 2 of the pipeline.

Takes the diagnosis and selects the action with the best expected recovery
value. The proposed action MUST go through validate_action() before execution.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.llm_client import get_llm
from backend.data.schema import (
    Diagnosis,
    FailureRecordInput,
    ProposedAction,
)

logger = logging.getLogger(__name__)


RECOVERY_SYSTEM_PROMPT = """You are a payment recovery action selection agent for an Indian recurring payment system.

Given a diagnosis of why a recurring payment failed, your task is to select the BEST recovery action that maximizes expected revenue recovery while respecting compliance and customer experience.

## AVAILABLE ACTIONS

1. **retry** — Schedule a payment retry. Only appropriate for insufficient_funds cases. Specify retry_delay_days (1-5 days).
2. **send_reminder** — Send a payment reminder notification to the customer.
3. **send_reauth_link** — Send a mandate re-authorization link. For expired mandates.
4. **send_stepup_auth** — Send step-up authentication prompt. For amounts exceeding auto-debit threshold (₹15,000).
5. **send_alternate_payment_prompt** — Ask customer for an alternate payment method. For genuine bank declines.
6. **hold_for_review** — Flag for manual review. For ambiguous cases.
7. **stop** — Take no action. For cancelled mandates, exhausted retries.

## EXPECTED VALUE REASONING

For each action, consider:
- **Expected Revenue Recovered**: Likelihood of successful recovery × amount
- **Cost of Intervention**: Operational cost of the action
- **Customer Friction Cost**: How much this action annoys/burdens the customer
- **Risk/Compliance Penalty**: Regulatory or reputational risk

Select the action with the highest: Expected Revenue Recovered − Cost − Friction − Risk

## RULES

- For `insufficient_funds`: retry is usually best. Choose timing based on when the customer is most likely to have funds (salary cycles, etc.)
- For `mandate_expired`: ONLY send_reauth_link is allowed (retry will fail)
- For `afa_required`: send_stepup_auth is the correct action
- For `genuine_decline`: send_alternate_payment_prompt (the current payment method has a technical issue)
- For `customer_cancelled`: stop (respect customer intent)
- For `ambiguous`: hold_for_review (don't act without diagnosis confidence)

## OUTPUT

Call the `propose_recovery_action` tool with your selected action, reasoning, and retry_delay_days (if applicable).
"""

RECOVERY_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_recovery_action",
        "description": "Propose a recovery action for the failed payment",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "retry",
                        "send_reminder",
                        "send_reauth_link",
                        "send_stepup_auth",
                        "send_alternate_payment_prompt",
                        "hold_for_review",
                        "stop",
                    ],
                },
                "reasoning": {
                    "type": "string",
                    "description": "Expected value reasoning for why this action was selected",
                },
                "retry_delay_days": {
                    "type": "integer",
                    "description": "For retry actions: number of days to delay (1-5). Null for non-retry actions.",
                },
            },
            "required": ["action", "reasoning"],
        },
    },
}


def _format_diagnosis_for_prompt(
    record: FailureRecordInput,
    diagnosis: Diagnosis,
) -> str:
    """Format diagnosis + record context for the Recovery Agent."""
    lines = [
        "## Diagnosis Result\n",
        f"- **Root Cause**: {diagnosis.root_cause}",
        f"- **Confidence**: {diagnosis.confidence:.2f}",
        f"- **Evidence**: {diagnosis.evidence}",
        "\n### Cause Evaluations:",
    ]

    for ce in diagnosis.cause_evaluations:
        lines.append(f"- **{ce.cause}**: {ce.verdict} — {ce.reason}")

    lines.extend([
        "\n## Payment Context\n",
        f"- **Amount**: ₹{record.amount:,.2f}",
        f"- **Mandate Status**: {record.mandate_status.value}",
        f"- **Mandate Type**: {record.mandate_type.value}",
        f"- **Retry Attempt**: {record.retry_attempt_number}",
        f"- **Prior Successful Payments**: {record.customer_prior_successful_payments}",
        f"- **Prior Failures**: {record.customer_prior_failures}",
    ])

    if record.customer_last_payment_date:
        lines.append(f"- **Last Successful Payment**: {record.customer_last_payment_date}")

    return "\n".join(lines)


async def run_recovery_agent(
    record: FailureRecordInput,
    diagnosis: Diagnosis,
) -> ProposedAction:
    """
    Run the Recovery Agent to propose an action.
    This is a PROPOSAL — it does NOT execute. Must go through validate_action().
    """
    llm = get_llm(temperature=0.1)

    prompt_text = _format_diagnosis_for_prompt(record, diagnosis)

    messages = [
        SystemMessage(content=RECOVERY_SYSTEM_PROMPT),
        HumanMessage(
            content=f"Select the best recovery action for this case:\n\n{prompt_text}"
        ),
    ]

    llm_with_tools = llm.bind_tools(
        [RECOVERY_TOOL],
        tool_choice={"type": "function", "function": {"name": "propose_recovery_action"}},
    )

    try:
        response = await llm_with_tools.ainvoke(messages)

        if not response.tool_calls:
            logger.warning(f"Recovery agent produced no tool call. Content: {response.content[:200]}")
            return _make_default_proposal(diagnosis)

        tool_call = response.tool_calls[0]
        args = tool_call.get("args", tool_call)

        return ProposedAction(
            action=args["action"],
            reasoning=args.get("reasoning", "No reasoning provided"),
            retry_delay_days=args.get("retry_delay_days"),
        )

    except Exception as e:
        logger.error(f"Recovery agent failed: {e}")
        return _make_default_proposal(diagnosis)


def _make_default_proposal(diagnosis: Diagnosis) -> ProposedAction:
    """Sensible default proposal when the LLM fails. Still goes through validate_action()."""
    action_map = {
        "insufficient_funds": ("retry", 2),
        "mandate_expired": ("send_reauth_link", None),
        "afa_required": ("send_stepup_auth", None),
        "customer_cancelled": ("stop", None),
        "genuine_decline": ("send_alternate_payment_prompt", None),
        "ambiguous": ("hold_for_review", None),
    }

    action, delay = action_map.get(diagnosis.root_cause, ("hold_for_review", None))

    return ProposedAction(
        action=action,
        reasoning=f"Default proposal for root_cause={diagnosis.root_cause} (LLM fallback)",
        retry_delay_days=delay,
    )
