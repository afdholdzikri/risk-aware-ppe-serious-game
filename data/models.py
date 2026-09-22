"""Validated, immutable scenario and trial records.

Identifiers are stable research codes, not presentation labels. Store a scenario
version alongside participant responses whenever scenarios are revised.
"""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class Condition(StrEnum):
    """Randomized experimental assignment."""

    CONTROL = "CONTROL"
    ADAPTIVE = "ADAPTIVE"


@dataclass(frozen=True, slots=True)
class Scenario:
    """One decision exposure with its required PPE and recognized hazards."""

    id: str
    hazard_id: str
    required_ppe: frozenset[str]
    critical_ppe: frozenset[str]
    expected_hazards: frozenset[str]
    control_order: int
    reinforcement_for: frozenset[str] = frozenset()
    version: str = "1.0"
    complexity: int = 1
    risk_priorities: tuple[tuple[str, float], ...] = ()
    risk_priority_source: str = "PILOT_UNVALIDATED"
    expert_validation_status: str = "pilot"
    primary_expert_panel_n: int | None = None
    followup_expert_panel_n: int | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.hazard_id or not self.version:
            raise ValueError("scenario ID, hazard ID, and version are required")
        if not self.critical_ppe <= self.required_ppe:
            raise ValueError("critical PPE must also be required PPE")
        if self.control_order < 0:
            raise ValueError("control_order must be nonnegative")
        if self.complexity < 1:
            raise ValueError("complexity must be positive")
        scores = dict(self.risk_priorities)
        if len(scores) != len(self.risk_priorities) or set(scores) != set(self.required_ppe):
            raise ValueError("risk priorities must cover each required PPE item exactly once")
        if any(not isfinite(value) or value <= 0 for value in scores.values()):
            raise ValueError("risk priorities must be finite and positive")
        if self.expert_validation_status not in {"pilot", "final"}:
            raise ValueError("unknown expert validation status")
        if self.expert_validation_status == "final" and not self.primary_expert_panel_n:
            raise ValueError("final scenarios require expert panel provenance")


@dataclass(frozen=True, slots=True)
class Decision:
    """Participant response for a single scenario exposure."""

    scenario_id: str
    selected_ppe: frozenset[str]
    identified_hazards: frozenset[str]


@dataclass(frozen=True, slots=True)
class Exposure:
    """Ordered result used by the adaptive selector and error-window rule."""

    scenario_id: str
    hazard_id: str
    safe: bool
    omitted_ppe: frozenset[str]
    decision_state: str = "UNSAFE"
    critical_error: bool = False
    complexity: int = 1
