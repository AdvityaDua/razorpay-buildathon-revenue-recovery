# AGENTS.md

This file is always loaded. Read `docs/PRD.md` in full before writing any code that touches the agent, data schema, or policy layer — it is the source of truth, not this file. This file tells you *how to work in this repo*; the PRD tells you *what to build*.

## Project

AI Recurring Revenue Recovery Orchestrator — Razorpay Buildathon, Track 03 (AI Revenue Recovery). A two-stage LLM agent (Diagnosis → Recovery Policy) that diagnoses why a recurring payment failed and selects a compliant recovery action, gated by a deterministic policy layer the LLM cannot override. Full spec: `docs/PRD.md`.

**Hard deadline: Sep 5, 2026. Build days remaining are limited — do not gold-plate. When in doubt, check PRD Section 4 (scope) and Section 4.3 (cut lines) before adding anything not listed there.**

## Stack (do not deviate without asking)

- Backend: FastAPI (Python)
- Agent orchestration: LangGraph + LangChain
- LLM: Llama 3.3 70B Instruct, self-hosted vLLM, OpenAI-compatible endpoint at the URL in `.env` (`LLM_BASE_URL`), native tool-calling enabled server-side
- Frontend: React + ShadCN + TanStack Query — **not Redux, not Redux Toolkit**
- Data: synthetic JSON/CSV or SQLite — no need for Postgres/heavier infra at this scale
- Explicitly not used: Celery, Django, Flask, any real SMS/WhatsApp sending, real payment execution

## Non-negotiable design rules

1. **The deterministic policy layer is pure code, never an LLM call.** See `docs/PRD.md` Section 7 for the full rule table and `.agents/skills/policy-layer-guard/SKILL.md` before touching `backend/agent/policy_rules.py`. The LLM proposes an action; `validate_action()` is the only thing that can authorize execution. If you're about to let an LLM output directly trigger an action with no `validate_action()` call in between, stop — that's a scope violation of the core product thesis, not a shortcut.
2. **`root_cause` must be self-consistent with `cause_evaluations`.** This was a reproduced, confirmed bug during prompt testing (PRD Section 12, finding 3) — the model will sometimes select a cause it never evaluated or already ruled out. Enforce this as a code-level validation on every Diagnosis Agent call, with a retry-once-then-flag-ambiguous fallback. Do not assume the prompt alone prevents this.
3. **Never trust a bare confidence score.** Confidence < 0.5 is treated as `ambiguous` regardless of the stated `root_cause`, per the policy table. This is a code-level gate, not a prompt instruction.
4. **All batch metrics are computed on the full batch, never on a cherry-picked subset.** If you're writing code that reports a single example's outcome as if it represents overall performance, stop and route it through `backend/eval/metrics.py` instead.
5. **Every agent decision writes an audit trail entry** — evidence considered, diagnosis, confidence, policy check result (including any override), action taken or withheld, and why. No silent actions.

## Where things live

- `docs/PRD.md` — full spec, read first
- `backend/agent/` — LangGraph nodes, policy rules, LLM client
- `backend/data/` — synthetic data schema + generator
- `backend/eval/` — batch runner, baseline comparator, metrics
- `backend/api/` — FastAPI app serving the frontend
- `frontend/src/pages/` — Recovery Queue page, Metrics page (only two pages in MVP scope)

## Working style expectations

- Prefer small, testable functions over large orchestration blocks — the policy layer especially must be unit-testable in isolation from any LLM call.
- When a PRD section is ambiguous or you need to make a judgment call not specified there, state the assumption in a code comment and keep moving — don't block on it, but don't silently guess on anything in Section 7 (the policy table) without flagging it.
- Do not introduce new Python/JS dependencies outside the locked stack without flagging it first — every added dependency costs review time we don't have.
- This is a synthetic-data project. Never fetch, request, or assume access to real Razorpay merchant/customer data.
