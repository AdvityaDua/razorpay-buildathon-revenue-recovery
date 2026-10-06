# AGENTS.md

This file contains the core principles for working on the RecoverIQ codebase.

## Project

RecoverIQ: AI Recurring Revenue Recovery Orchestrator. A two-stage LLM agent (Diagnosis → Recovery Policy) that diagnoses why a recurring payment failed and selects a compliant recovery action, gated by a deterministic policy layer the LLM cannot override.

## Stack (do not deviate)

- Backend: FastAPI (Python)
- Agent orchestration: LangGraph + LangChain
- LLM: NVIDIA Nemotron, OpenAI-compatible endpoint
- Frontend: React + ShadCN + TanStack Query
- Data: synthetic JSON

## Non-negotiable design rules

1. **The deterministic policy layer is pure code, never an LLM call.** The LLM proposes an action; `validate_action()` in `policy_rules.py` is the only thing that can authorize execution.
2. **`root_cause` must be self-consistent with `cause_evaluations`.** Enforce this as a code-level validation on every Diagnosis Agent call, with a retry-once-then-flag-ambiguous fallback.
3. **Never trust a bare confidence score.** Confidence < 0.5 is treated as `ambiguous` regardless of the stated `root_cause`. This is a code-level gate.
4. **All batch metrics are computed on the full batch, never on a cherry-picked subset.** Route all metrics through `backend/eval/metrics.py`.
5. **Every agent decision writes an audit trail entry** — evidence considered, diagnosis, confidence, policy check result (including any override), action taken or withheld, and why. No silent actions.

## Where things live

- `backend/agent/` — LangGraph nodes, policy rules, LLM client
- `backend/data/` — synthetic data schema + generator
- `backend/eval/` — batch runner, baseline comparator, metrics
- `backend/api/` — FastAPI app serving the frontend
- `frontend/src/` — React application

## Working style expectations

- Prefer small, testable functions over large orchestration blocks.
- This is a synthetic-data project. Never fetch, request, or assume access to real payment gateway data.
