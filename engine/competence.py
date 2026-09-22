"""Per-hazard competence and progression state transitions."""

from dataclasses import dataclass

from app.config import DEFAULT_POLICY, PolicyConfig


@dataclass(frozen=True, slots=True)
class CompetenceState:
    """Current estimate and consecutive Safe streak for one hazard."""

    value: float
    consecutive_safe: int = 0


def initial_state(policy: PolicyConfig = DEFAULT_POLICY) -> CompetenceState:
    """Create the fixed initial estimate for a previously unseen hazard."""
    return CompetenceState(policy.initial_competence)


def update_competence(
    state: CompetenceState, pdss: float, decision_state: str,
    policy: PolicyConfig = DEFAULT_POLICY,
) -> CompetenceState:
    """Smooth normalized PDSS and update the Safe decision streak.

    The score contributes even to Risky or Unsafe decisions. Only Safe
    decisions extend the streak.
    """
    if not 0 <= state.value <= 1 or state.consecutive_safe < 0:
        raise ValueError("invalid competence state")
    if not 0 <= pdss <= 100 or decision_state not in {"SAFE", "RISKY", "UNSAFE"}:
        raise ValueError("invalid score or decision state")
    value = policy.alpha * (pdss / 100.0) + (1.0 - policy.alpha) * state.value
    value = min(1.0, max(0.0, value))
    return CompetenceState(value, state.consecutive_safe + 1 if decision_state == "SAFE" else 0)


def can_progress(state: CompetenceState, policy: PolicyConfig = DEFAULT_POLICY) -> bool:
    """Require both competence threshold and consecutive Safe decisions."""
    return state.value >= policy.progression_threshold and state.consecutive_safe >= policy.consecutive_safe_required
