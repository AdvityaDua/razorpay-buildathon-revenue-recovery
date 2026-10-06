"""
Diagnosis Agent — Stage 1 of the recovery pipeline.

Evaluates all 5 possible failure causes individually, then selects the most
likely root cause with a calibrated confidence score. Includes self-consistency
validation and a confidence gate.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.llm_client import get_llm
from backend.data.schema import (
    CauseEvaluation,
    Diagnosis,
    FailureRecordInput,
)

logger = logging.getLogger(__name__)

DIAGNOSIS_SYSTEM_PROMPT = """You are a payment failure diagnosis agent for an Indian recurring payment (subscription/mandate auto-debit) system.

Your task: Given a failed recurring payment record, diagnose WHY it failed by evaluating all possible causes, then select the most likely root cause with a calibrated confidence score.

## MANDATORY REASONING PROCEDURE

You MUST evaluate ALL 5 possible causes individually before selecting a root cause. For each cause, determine if it is "plausible" or "ruled_out" based on the evidence in the payment record.

The 5 causes to evaluate are:
1. **insufficient_funds** — Temporary balance shortfall. Look for: error codes mentioning funds/balance, active mandate, customer with prior successful payments.
2. **mandate_expired** — Mandate validity period lapsed. Look for: mandate_status == expired, mandate age exceeding validity_days, error codes mentioning expiry.
3. **afa_required** — Amount crossed the ₹15,000 no-auth threshold, step-up auth not completed. Look for: amount > 15000, error codes mentioning authentication.
4. **customer_cancelled** — Customer paused/revoked mandate. Look for: mandate_status == revoked or paused, error codes mentioning revocation/cancellation.
5. **genuine_decline** — Explicit bank/network technical decline. Look for: non-null error_code/error_reason/error_source indicating a technical issue. IMPORTANT: genuine_decline may ONLY be marked "plausible" if at least one error signal field (error_code, error_reason, error_source, error_step) is non-null. Absence of error fields is NOT evidence for a technical cause.

## CONFIDENCE CALIBRATION RULES

- **≥ 0.8**: Use ONLY when 2 or more independent signals agree (e.g., error_code matches AND mandate_status is consistent AND customer history supports it)
- **0.5 – 0.79**: Use when there is one clear primary signal with supporting context
- **< 0.5**: Use when evidence is weak, generic, or conflicting. This is the DEFAULT for cases with null error fields and no strong secondary signals.

## ROOT CAUSE SELECTION RULES

- Your selected root_cause MUST be one of the causes you marked as "plausible" in your evaluations, OR "ambiguous" if no cause has strong positive support.
- If multiple causes are plausible, pick the one with strongest positive evidence (not elimination).
- If no cause has strong positive support, select "ambiguous" — do NOT guess.
- "ambiguous" is a legitimate and expected diagnosis for ~20% of cases. Do not avoid it.

## NULL ERROR FIELDS

Error fields (error_code, error_reason, error_source, error_step) are frequently ALL null (~30-40% of real webhooks). This is NORMAL. When error fields are null:
- You must still evaluate all 5 causes using secondary signals (mandate_status, amount, customer history, timing)
- Do NOT default to genuine_decline — it requires positive error signals
- Lower your confidence appropriately (typically < 0.5 for weak evidence)

## OUTPUT FORMAT

You must call the `diagnose_failure` tool with your structured diagnosis.
"""

DIAGNOSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "diagnose_failure",
        "description": "Submit the structured diagnosis for a failed recurring payment",
        "parameters": {
            "type": "object",
            "properties": {
                "cause_evaluations": {
                    "type": "array",
                    "description": "Evaluation of all 5 non-ambiguous causes",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cause": {
                                "type": "string",
                                "enum": [
                                    "insufficient_funds",
                                    "mandate_expired",
                                    "afa_required",
                                    "customer_cancelled",
                                    "genuine_decline",
                                ],
                            },
                            "verdict": {
                                "type": "string",
                                "enum": ["ruled_out", "plausible"],
                            },
                            "reason": {
                                "type": "string",
                                "description": "Must cite specific input field names and values",
                            },
                        },
                        "required": ["cause", "verdict", "reason"],
                    },
                },
                "root_cause": {
                    "type": "string",
                    "enum": [
                        "insufficient_funds",
                        "mandate_expired",
                        "afa_required",
                        "customer_cancelled",
                        "genuine_decline",
                        "ambiguous",
                    ],
                },
                "confidence": {
                    "type": "number",
                    "description": "0-1 confidence score, calibrated per the rules above",
                },
                "evidence": {
                    "type": "string",
                    "description": "Must cite specific field names and their values from the input",
                },
            },
            "required": ["cause_evaluations", "root_cause", "confidence", "evidence"],
        },
    },
}


def _format_record_for_prompt(record: FailureRecordInput) -> str:
    """Format a failure record as readable key-value pairs for the LLM."""
    data = record.model_dump(mode="json")
    lines = ["## Payment Failure Record\n"]
    for key, value in data.items():
        if value is None:
            lines.append(f"- **{key}**: null")
        else:
            lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)


def _validate_diagnosis_consistency(diagnosis: Diagnosis) -> bool:
    """
    Check that root_cause appears as 'plausible' in cause_evaluations,
    or is 'ambiguous'. Catches the known failure mode where the model
    selects a cause it never evaluated or already ruled out.
    """
    if diagnosis.root_cause == "ambiguous":
        return True

    plausible_causes = {
        ce.cause for ce in diagnosis.cause_evaluations
        if ce.verdict == "plausible"
    }

    return diagnosis.root_cause in plausible_causes


def _parse_tool_call_to_diagnosis(tool_call: dict) -> Diagnosis:
    """Parse an LLM tool call response into a Diagnosis object."""
    args = tool_call.get("args", tool_call)

    cause_evaluations = [
        CauseEvaluation(**ce) for ce in args["cause_evaluations"]
    ]

    return Diagnosis(
        cause_evaluations=cause_evaluations,
        root_cause=args["root_cause"],
        confidence=float(args["confidence"]),
        evidence=args["evidence"],
    )


async def run_diagnosis(
    record: FailureRecordInput,
    max_retries: int = 1,
) -> Diagnosis:
    """
    Run the Diagnosis Agent on a single failure record.

    Validates self-consistency (retry once on failure, then flag ambiguous)
    and applies the confidence gate (< 0.5 → ambiguous).
    """
    llm = get_llm(temperature=0.1)

    record_text = _format_record_for_prompt(record)

    messages = [
        SystemMessage(content=DIAGNOSIS_SYSTEM_PROMPT),
        HumanMessage(content=f"Diagnose this failed payment:\n\n{record_text}"),
    ]

    llm_with_tools = llm.bind_tools(
        [DIAGNOSIS_TOOL],
        tool_choice={"type": "function", "function": {"name": "diagnose_failure"}},
    )

    for attempt in range(max_retries + 1):
        try:
            response = await llm_with_tools.ainvoke(messages)

            if not response.tool_calls:
                logger.warning(
                    f"Diagnosis attempt {attempt + 1}: No tool call in response. "
                    f"Content: {response.content[:200]}"
                )
                if attempt < max_retries:
                    continue
                return _make_ambiguous_fallback(
                    "LLM did not produce a tool call after retries"
                )

            tool_call = response.tool_calls[0]
            diagnosis = _parse_tool_call_to_diagnosis(tool_call)

            # Self-consistency: root_cause must match a plausible evaluation
            if not _validate_diagnosis_consistency(diagnosis):
                logger.warning(
                    f"Diagnosis attempt {attempt + 1}: Self-consistency violation — "
                    f"root_cause '{diagnosis.root_cause}' not in plausible causes "
                    f"{[ce.cause for ce in diagnosis.cause_evaluations if ce.verdict == 'plausible']}"
                )
                if attempt < max_retries:
                    messages.append(response)
                    messages.append(
                        HumanMessage(
                            content=(
                                "ERROR: Your root_cause selection is inconsistent. "
                                "The root_cause MUST be one of the causes you marked "
                                "'plausible', or 'ambiguous'. Please re-evaluate and "
                                "call diagnose_failure again."
                            )
                        )
                    )
                    continue
                logger.warning(
                    f"Self-consistency failed after {max_retries + 1} attempts. "
                    f"Flagging as ambiguous."
                )
                diagnosis.root_cause = "ambiguous"
                diagnosis.confidence = min(diagnosis.confidence, 0.3)

            # Confidence gate: < 0.5 → force ambiguous
            if diagnosis.confidence < 0.5 and diagnosis.root_cause != "ambiguous":
                logger.info(
                    f"Confidence gate: {diagnosis.confidence:.2f} < 0.5, "
                    f"overriding root_cause from '{diagnosis.root_cause}' to 'ambiguous'"
                )
                diagnosis.root_cause = "ambiguous"

            return diagnosis

        except Exception as e:
            logger.error(f"Diagnosis attempt {attempt + 1} failed with error: {e}")
            if attempt < max_retries:
                continue
            return _make_ambiguous_fallback(f"LLM error after retries: {e}")

    return _make_ambiguous_fallback("Exhausted all attempts")


def _make_ambiguous_fallback(reason: str) -> Diagnosis:
    """Create an ambiguous diagnosis as a safe fallback."""
    return Diagnosis(
        cause_evaluations=[
            CauseEvaluation(
                cause="insufficient_funds",
                verdict="ruled_out",
                reason=f"Unable to evaluate — {reason}",
            ),
            CauseEvaluation(
                cause="mandate_expired",
                verdict="ruled_out",
                reason=f"Unable to evaluate — {reason}",
            ),
            CauseEvaluation(
                cause="afa_required",
                verdict="ruled_out",
                reason=f"Unable to evaluate — {reason}",
            ),
            CauseEvaluation(
                cause="customer_cancelled",
                verdict="ruled_out",
                reason=f"Unable to evaluate — {reason}",
            ),
            CauseEvaluation(
                cause="genuine_decline",
                verdict="ruled_out",
                reason=f"Unable to evaluate — {reason}",
            ),
        ],
        root_cause="ambiguous",
        confidence=0.0,
        evidence=f"Fallback to ambiguous: {reason}",
    )
