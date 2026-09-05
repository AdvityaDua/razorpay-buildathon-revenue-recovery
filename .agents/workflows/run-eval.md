Run the full batch evaluation and report results.

1. Confirm `backend/data/dataset.json` exists and has 300-500 records; if not, run the generator first (`backend/data/generate_synthetic.py`) and confirm it followed PRD Section 6.3 (realistic null-field rate ~30%, ambiguous case rate ~20-30%).
2. Run `backend/eval/run_batch.py` end to end — full dataset, both the system-under-test and the naive baseline, per `.agents/skills/eval-harness-conventions/SKILL.md`.
3. Save the output report to `backend/eval/runs/<timestamp>.json`.
4. Print a summary table to console: diagnosis precision/recall per class, self-consistency rate, ₹ recovered (system vs baseline), % correctly stopped, false diagnoses by class, policy override count.
5. Flag anything that looks structurally wrong (e.g., 0% or 100% on any metric, which usually indicates a bug rather than a genuinely perfect/failed system) rather than reporting it uncritically.
