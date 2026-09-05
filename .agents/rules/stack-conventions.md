# Rule: Stack Conventions

## Python (backend)

- Python 3.11+, type hints on every function signature, Pydantic v2 models for all structured data (schemas defined in `backend/data/schema.py` are canonical — import them, don't redefine).
- LangGraph state is a `TypedDict` or Pydantic model, defined once in `backend/agent/graph.py`. Do not pass loose dicts between nodes.
- LLM client: `langchain_openai.ChatOpenAI` pointed at `LLM_BASE_URL` from `.env`, `temperature=0.1` for Diagnosis Agent calls (reproducibility matters for eval — see PRD Section 12, finding 5). Never hardcode the endpoint URL or model name inline; read from config.
- Structured LLM output: use `.with_structured_output()` bound to the Pydantic schemas in PRD Section 9. Native tool-calling is confirmed working against this deployment — do not fall back to manual JSON-string parsing unless `.with_structured_output()` demonstrably fails.
- All I/O-bound LLM/API calls should be `async def` — FastAPI and LangGraph both support this natively, use it for the batch eval runner so 300-500 records don't run fully serially.

## Frontend

- React function components only, TypeScript.
- Server state (API data) via TanStack Query hooks in `frontend/src/api/` — one hook per endpoint, colocate the query key with the hook.
- Local/UI-only state via `useState`/`useReducer` — no Redux, no global client-state library. If you find yourself wanting global state, that's a signal to lift the query up via TanStack Query instead, not to reach for Redux.
- ShadCN components: install only the specific components used (`npx shadcn add <component>`), don't bulk-install the whole library.
- Two pages only for MVP: Recovery Queue, Metrics. Do not scaffold auth, settings, or multi-tenant pages unless the PRD scope changes.

## General

- No `console.log`/`print` debugging left in committed code — use proper logging (`logging` module in Python, minimal in frontend).
- Every new file should map to a location already defined in `AGENTS.md`'s "Where things live" section. If it doesn't fit, that's a signal to ask before creating a new top-level structure.
- Commit messages: short, imperative, reference the PRD section when relevant (e.g. "Implement policy rule table (PRD §7)").
