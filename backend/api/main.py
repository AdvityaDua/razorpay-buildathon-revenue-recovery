"""
FastAPI application — serves the dashboard frontend.

Routes:
- GET /api/records — batch results (failure records + diagnosis + action + outcome)
- GET /api/metrics — computed metrics report (reads from eval output)
- POST /api/batch/run — trigger a batch run

Frontend Metrics page reads from saved eval report artifact, not
recomputing live (eval-harness-conventions rule 5).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Revenue Recovery Orchestrator",
    description="Razorpay Buildathon — Track 03: AI Revenue Recovery",
    version="0.1.0",
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # single demo merchant, no auth (PRD §4.2)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EVAL_RUNS_DIR = Path(__file__).parent.parent / "eval" / "runs"


def _load_latest_report() -> dict | None:
    """Load the latest batch report."""
    latest_path = EVAL_RUNS_DIR / "latest_report.json"
    if not latest_path.exists():
        return None
    with open(latest_path) as f:
        return json.load(f)


@app.get("/api/health")
async def health():
    """Health check."""
    return {"status": "ok"}


@app.get("/api/records")
async def get_records():
    """
    Get batch results — failure records with diagnosis, action, outcome.

    Reads from the latest eval report artifact.
    """
    report = _load_latest_report()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No batch report found. Run a batch evaluation first.",
        )

    return {
        "records": report.get("audit_entries", []),
        "metadata": report.get("metadata", {}),
    }


@app.get("/api/metrics")
async def get_metrics():
    """
    Get computed metrics — reads from saved eval report.

    Does NOT recompute metrics live (eval-harness-conventions rule 5).
    """
    report = _load_latest_report()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No batch report found. Run a batch evaluation first.",
        )

    return {
        "metrics": report.get("metrics", {}),
        "metadata": report.get("metadata", {}),
    }


@app.get("/api/baseline")
async def get_baseline():
    """Get baseline results."""
    report = _load_latest_report()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No batch report found. Run a batch evaluation first.",
        )

    return {
        "baseline_results": report.get("baseline_results", []),
        "metadata": report.get("metadata", {}),
    }


@app.post("/api/batch/run")
async def trigger_batch_run(background_tasks: BackgroundTasks):
    """
    Trigger a batch evaluation run.

    Runs in background so the API doesn't block.
    """
    from backend.eval.run_batch import run_batch

    async def _run():
        try:
            await run_batch()
        except Exception as e:
            logger.error(f"Batch run failed: {e}")

    background_tasks.add_task(asyncio.coroutine(_run) if not asyncio.iscoroutinefunction(_run) else _run)

    return {
        "status": "started",
        "message": "Batch evaluation started in background. Check /api/metrics for results.",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
