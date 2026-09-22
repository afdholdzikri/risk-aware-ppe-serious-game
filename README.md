# Risk-Aware PPE Serious Game

Python 3.12 playable research MVP for a two-condition PPE decision experiment. The decision rules remain testable independently of Streamlit.

## Setup

```bash
python -m venv .venv
pip install -e ".[test]"
pytest
streamlit run app/main.py
```

Set `DATABASE_URL` for PostgreSQL through an environment variable or `.streamlit/secrets.toml` (see the examples). Environment variables take precedence. Without either, submitted interactions are saved to `database/ppe_game.db` with SQLite. No credentials are stored in source code. Database tables are created on first participant start. The condition selector is intended for a study facilitator in this MVP; research-grade assignment and migrations are future work.

The app uses Streamlit `session_state` for the active run and logs each submitted interaction before advancing. Closing the browser loses the temporary run state, but submitted rows remain in the database. Both conditions run exactly 12 training attempts. Control follows S1A–S6A, then S1B–S6B; adaptive selection uses the same twelve-card bank. The app also runs 12 blinded pre-test and 12 blinded post-test items.

## Research database

The schema has four linked tables:

| Table | Purpose |
| --- | --- |
| `participants` | Pseudonymous study code, stable participant ID, assigned group |
| `sessions` | One run per participant, group, start/end time, status |
| `training_logs` | One complete decision record per attempt, including score, critical error, timing, competence transition, remedial target, and next scenario |
| `assessment_logs` | Pre/post assessment records for later study phases |

`training_logs` has a unique `(session_id, attempt)` pair and foreign keys to the participant and session. Identical rerun submissions are idempotent. `decision_time` is elapsed seconds from scenario presentation to submission. `reinforcement_focus` is a `hazard_id:ppe_id` code when applicable; `next_scenario` is null at the twelfth attempt. Earlier `training_logs` tables receive additive columns without deleting prior rows. The old `interaction_log` table, if present, remains untouched.

## Decision rules

- `CONTROL` uses scenario `control_order` and standard feedback.
- `ADAPTIVE` uses PDSS, critical-PPE enforcement, competence updates, and targeted reinforcement.
- PDSS is `100 × (1 − sum(normalized risk priorities for omitted required PPE))`. Normalized weights are calculated from the stored unrounded priority values when scoring. Over-selection does not reduce PDSS.
- PPE Requirement Coverage is required items selected divided by required items; exact decision accuracy (PDA) is 1 only for exact set equality. Hazard recognition is `TP / (TP + FP + FN) × 100`.
- Every missing critical item forces Unsafe. `THETA_HIGH = 80` and `THETA_LOW = 60` are centralized, **pilot-locked; verify before the main experiment**. They are not expert-validated thresholds. Noncritical PDSS ≥ 80 is Safe, 60–79.99 is Risky, and below 60 is Unsafe.
- Competence updates as `0.4 × (PDSS / 100) + 0.6 × previous competence`, independently for each hazard. Initial competence is 0.5.
- Progression requires competence at least 0.80 and two consecutive Safe decisions for the same hazard.
- A repeated error means the same `(hazard_id, ppe_id)` omission occurred at least twice in the three latest exposures relevant to that pair. Exposures without the error still count in that window.
- Adaptive selection prioritizes critical omissions, Unsafe decisions, Risky reinforcement, progressed Safe decisions, then comparable complexity. Exact immediate repetition is avoided when an equivalent alternative exists.

All policy values are in `app/config.py`. The six domains, expert median risk-priority scores, critical PPE, and scenario-defined hazard sets are in `data/scenarios.json`. Catalog IDs and labels are in `data/ppe_catalog.json` and `data/hazard_catalog.json`. Twelve training narratives are in `data/training_cards.json`; 24 assessment narratives are in `data/assessment_items.json`. The UI shows only the 4–6 candidates listed for the active domain. S3 face shield and S6 high-visibility vest are excluded from PDSS ground truth. Contextual PPE is marked non-scored; insulated tools are not PPE.

The PPE requirement sets, critical designations, and median priorities have final expert-panel provenance (`n = 13`; S5 follow-up `n = 13`). The hazard sets are **scenario-defined hazard sets derived from the expert-reviewed workplace scenarios**; they were not independently rated as a separate quantitative expert question. The A/B and pre/post variants are protocol-defined equivalent content, not independently expert-validated items. See `AUDIT_REPORT.md` for the full implementation status.
