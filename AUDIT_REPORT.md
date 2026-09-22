# Audit report — Risk-Aware PPE Serious Game

Updated 22 September 2026. This report records the current protocol implementation and the earlier inconsistencies that were resolved. The existing Streamlit visual design remains in place.

## 1. Current implementation

The application has landing, participant, blinded pre-test, training, feedback, blinded post-test, and completion screens. Streamlit `session_state` holds temporary play state; SQLAlchemy persists participants, sessions, training decisions, and assessment results to SQLite locally or a configured PostgreSQL database. Control and adaptive conditions both run exactly 12 training attempts.

Ground truth for the six domains is centralized in `data/scenarios.json`. The two catalog files define selectable PPE and hazards. `data/training_cards.json` defines the 12 training narratives. `data/assessment_items.json` defines 12 PRE and 12 POST narratives. Loaders inherit validated domain truth and candidate choices rather than copying answer keys into the UI.

The PPE requirement sets, critical PPE, and median risk-priority scores are final expert-panel parameters (`primary_expert_panel_n = 13`; S5 follow-up `n = 13`). The hazard sets are **scenario-defined hazard sets derived from the expert-reviewed workplace scenarios**. They were not independently rated as a separate quantitative expert question. Training A/B wording is protocol-derived; PRE/POST wording is **protocol-defined equivalent assessment content**, not independently expert-validated items.

## 2. Inconsistencies found and resolved

| Earlier state | Resolution |
| --- | --- |
| PDSS used a weighted PPE/hazard accuracy on a 0–1 scale | PDSS now uses omitted required PPE weighted by unrounded expert median priorities and is constrained to 0–100 |
| PPE coverage, exact accuracy, over-selection, and hazard recognition were conflated | RC, PDA, OS, and HRA are calculated independently and logged |
| Competence used a binary Safe target | Competence now smooths `PDSS / 100`; only Safe extends the streak |
| Decision thresholds were incomplete | `THETA_HIGH = 80`, `THETA_LOW = 60` are centralized and pilot-locked |
| Four pilot cards were repeated, and the adaptive condition could end early | The bank now contains S1A–S6A and S1B–S6B; both groups complete 12 attempts |
| Pre/post item IDs and counts were unspecified | PRE01–PRE12 and POST01–POST12 are present, two per domain |
| Old global PPE/hazard choices included mismatched items | Scenario-specific 4–6 candidate choices are loaded from JSON; every required PPE and true hazard is selectable |
| Training and assessment logging lacked some research variables | Full training fields and internally calculated assessment metrics are persisted; repeat writes for a training attempt or assessment item are idempotent |

## 3. Research parameters and protocol rules

| Parameter | Current value or rule | Status |
| --- | --- | --- |
| `THETA_HIGH` | 80/100 | **pilot-locked; verify before the main experiment** |
| `THETA_LOW` | 60/100 | **pilot-locked; verify before the main experiment** |
| Decision classification | Critical omission → Unsafe; otherwise PDSS ≥ 80 → Safe, PDSS ≥ 60 → Risky, PDSS < 60 → Unsafe | Protocol rule; thresholds are not expert-validated |
| `alpha` | 0.4 | Fixed research parameter |
| Initial competence | 0.5 | Fixed research parameter |
| Competence update | `0.4 × PDSS/100 + 0.6 × previous` | Fixed research rule |
| Progression | Competence ≥ 0.80 and Safe streak ≥ 2 | Fixed research rule |
| Repeated error | Same hazard–PPE omission at least twice in the latest three relevant exposures | Fixed research rule |
| PDSS | `100 × (1 − sum(priority of omitted required PPE / sum(required PPE priorities)))` | Expert medians normalized at runtime, never rounded internally |
| Required PPE coverage | Required PPE selected / total required PPE × 100 | Logged and displayed in adaptive training |
| PDA | 1 only for exact selected/required PPE set equality | Logged research variable |
| Over-selection | Count of selected PPE outside the required set | Logged; never deducted from PDSS |
| HRA | `TP / (TP + FP + FN) × 100` | Scored against scenario-defined hazards |
| Critical error | Any missing critical PPE forces Unsafe | Fixed research rule |
| Training cards | S1A–S6A, then S1B–S6B in Control; same bank with adaptive selection in Adaptive | Exactly 12 attempts per group |
| Assessment items | PRE01–PRE12 and POST01–POST12 | Two items per domain per phase |
| Policy version | `3.0-protocol` | Logged with decisions |

Validated PPE parameter provenance remains in the domain JSON and trial logs: `expert_validation_status = "final"`, primary panel `n = 13`, and S5 follow-up panel `n = 13`. S5's four final required PPE items had 100% follow-up requirement agreement. Critical consensus was 100% for electrical protective gloves, safety footwear, and eye/face protection, and 92.3% for the safety helmet. S3 face shield and S6 high-visibility vest remain outside the PDSS requirement sets. Arc-rated clothing is contextual and non-scored; insulated tools are not PPE.

## 4. Sequence and blinding

Control uses the fixed order `S1A, S2A, S3A, S4A, S5A, S6A, S1B, S2B, S3B, S4B, S5B, S6B`. Adaptive selection uses the same twelve-card bank and prioritizes critical omissions, Unsafe remediation, Risky reinforcement, progressed Safe decisions, then comparable complexity. When an equivalent eligible A/B card exists, selection avoids immediately repeating the same variant.

Each PRE and POST item offers hazard recognition and PPE selection, with all true options and irrelevant distractors. Assessment screens never display PDSS, PDA, PPE coverage, correctness, missing PPE, critical status, competence, safe streak, reinforcement focus, or recommended answers. They still store HRA, PDA, coverage, PDSS, critical error, over-selection, and decision time internally.

## 5. Verification

- `python -m pytest -q` → **36 passed, 0 failed**.
- Tests cover the exact threshold boundaries (80, 79.99, 60, below 60), critical override, 12 control and adaptive attempts, fixed control order, all six domains, A/B ground-truth equality, all 24 assessment IDs and domain mappings, pre/post blinding, persisted assessment metrics, and the validated PPE catalog.
- SQLite is used for local and automated tests. PostgreSQL DDL compilation is covered; no live PostgreSQL integration server was available.
- Built a wheel and confirmed all five JSON catalog/domain/variant data files are included.
- `python -m streamlit run app/main.py --server.headless true --server.port 8506` started successfully; `/_stcore/health` returned HTTP 200. The normal command remains `python -m streamlit run app/main.py`.

## Remaining issues

No requested protocol input remains missing from this implementation. The two pilot-locked thresholds require verification before the main experiment, as explicitly directed. The A/B and assessment variant wording is protocol-derived and should be checked against the final approved participant materials; it is not represented as separately expert-validated. A live PostgreSQL integration test remains to be run in the production environment.
