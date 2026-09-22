"""Risk-priority PDSS and independent research outcome measures."""

from dataclasses import dataclass

from app.config import DEFAULT_POLICY, PolicyConfig
from data.models import Decision, Scenario


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """Full decision result; public percentages are on a 0–100 scale."""

    pdss: float
    required_ppe_coverage: float
    pda: int
    extra_ppe: frozenset[str]
    os: int
    hra: float
    missing_critical_ppe: frozenset[str]
    omitted_ppe: frozenset[str]
    critical_error: bool
    decision_state: str

    @property
    def safe(self) -> bool:
        """Compatibility helper for the progression rule."""
        return self.decision_state == "SAFE"


def critical_ppe_missing(scenario: Scenario, decision: Decision) -> frozenset[str]:
    """Return every expert-designated critical item omitted."""
    return scenario.critical_ppe - decision.selected_ppe


def hazard_recognition_accuracy(expected: frozenset[str], selected: frozenset[str]) -> float:
    """Calculate TP/(TP+FP+FN) × 100 without rewarding select-all."""
    tp = len(expected & selected)
    denominator = len(expected | selected)
    return 100.0 * tp / denominator if denominator else 100.0


def score_decision(
    scenario: Scenario, decision: Decision, policy: PolicyConfig = DEFAULT_POLICY,
) -> ScoreResult:
    """Calculate PDSS from unrounded priorities and classify the decision.

    Critical omissions override both pilot-locked thresholds. Noncritical
    scores are Safe at 80+, Risky at 60–79.99, and Unsafe below 60.
    """
    if decision.scenario_id != scenario.id:
        raise ValueError("decision scenario_id does not match scenario")
    priorities = dict(scenario.risk_priorities)
    total = sum(priorities.values())
    omitted = scenario.required_ppe - decision.selected_ppe
    rr = sum(priorities[ppe] / total for ppe in omitted) if total else 0.0
    pdss = min(100.0, max(0.0, 100.0 * (1.0 - rr)))
    coverage = (100.0 * len(scenario.required_ppe & decision.selected_ppe) / len(scenario.required_ppe)
                if scenario.required_ppe else 100.0)
    extra = decision.selected_ppe - scenario.required_ppe
    critical_missing = critical_ppe_missing(scenario, decision)
    if critical_missing or pdss < policy.theta_low:
        state = "UNSAFE"
    elif pdss >= policy.theta_high:
        state = "SAFE"
    else:
        state = "RISKY"
    return ScoreResult(
        pdss=pdss,
        required_ppe_coverage=coverage,
        pda=int(decision.selected_ppe == scenario.required_ppe),
        extra_ppe=extra,
        os=len(extra),
        hra=hazard_recognition_accuracy(scenario.expected_hazards, decision.identified_hazards),
        missing_critical_ppe=critical_missing,
        omitted_ppe=omitted,
        critical_error=bool(critical_missing),
        decision_state=state,
    )
