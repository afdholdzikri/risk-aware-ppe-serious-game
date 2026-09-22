"""Reproducible fixed and adaptive scenario selection."""

from collections import Counter
from collections.abc import Mapping, Sequence

from app.config import DEFAULT_POLICY, PolicyConfig
from data.models import Condition, Exposure, Scenario
from engine.competence import CompetenceState, can_progress, initial_state


def repeated_errors(
    exposures: Sequence[Exposure], policy: PolicyConfig = DEFAULT_POLICY
) -> frozenset[tuple[str, str]]:
    """Find PPE omissions repeated in the latest relevant hazard exposures.

    Relevance is defined by hazard ID. For each hazard, take its three latest
    exposures and count each omitted PPE code within that window.
    """
    hazards = {item.hazard_id for item in exposures}
    found: set[tuple[str, str]] = set()
    for hazard in hazards:
        recent = [item for item in exposures if item.hazard_id == hazard][-policy.repeated_error_window:]
        counts = Counter(ppe for item in recent for ppe in item.omitted_ppe)
        found.update((hazard, ppe) for ppe, count in counts.items() if count >= policy.repeated_error_count)
    return frozenset(found)


def select_scenario(
    scenarios: Sequence[Scenario], condition: Condition,
    exposures: Sequence[Exposure] = (),
    competence: Mapping[str, CompetenceState] | None = None,
    policy: PolicyConfig = DEFAULT_POLICY,
) -> Scenario | None:
    """Select fixed control or state-dependent adaptive training exposure.

    Priority is critical omission, Unsafe, Risky, progressed Safe, then
    comparable complexity. Stable tie-breaking keeps replay deterministic.
    """
    if len({s.id for s in scenarios}) != len(scenarios):
        raise ValueError("scenario IDs must be unique")
    if not scenarios:
        return None
    counts = Counter(item.scenario_id for item in exposures)
    if condition == Condition.CONTROL:
        ordered = sorted(scenarios, key=lambda s: (s.control_order, s.id))
        return ordered[len(exposures) % len(ordered)] if len(exposures) < policy.training_attempts else None
    if condition != Condition.ADAPTIVE:
        raise ValueError("unknown experimental condition")
    if len(exposures) >= policy.training_attempts:
        return None
    if not exposures:
        return min(scenarios, key=lambda s: (s.complexity, s.control_order, s.id))
    last = exposures[-1]
    errors = repeated_errors(exposures, policy)
    omitted = last.omitted_ppe
    targeted = [s for s in scenarios if s.hazard_id == last.hazard_id and
                bool(s.reinforcement_for & omitted or
                     any((s.hazard_id, ppe) in errors for ppe in s.reinforcement_for))]
    comparable = [s for s in scenarios if s.complexity == last.complexity]
    nearby = [s for s in scenarios if abs(s.complexity - last.complexity) <= 1]
    if last.critical_error:
        pool = targeted or [s for s in scenarios if s.hazard_id == last.hazard_id and s.complexity <= last.complexity]
    elif last.decision_state == "UNSAFE":
        pool = targeted or [s for s in scenarios if s.hazard_id == last.hazard_id and s.complexity <= last.complexity]
    elif last.decision_state == "RISKY":
        pool = [s for s in targeted if s in nearby] or comparable
    elif last.decision_state == "SAFE" and can_progress(
        (competence or {}).get(last.hazard_id, initial_state(policy)), policy
    ):
        pool = [s for s in scenarios if s.complexity > last.complexity]
    else:
        pool = comparable
    pool = pool or list(scenarios)
    alternatives = [s for s in pool if s.id != last.scenario_id]
    if alternatives:
        pool = alternatives
    return min(pool, key=lambda s: (counts[s.id], abs(s.complexity - last.complexity), s.control_order, s.id))
