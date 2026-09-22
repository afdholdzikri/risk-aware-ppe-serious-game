"""Versioned research policy parameters.

Override these values by constructing a new PolicyConfig; avoid silently changing
them during an experimental run. Persist the policy version with trial data.
"""

from dataclasses import dataclass


THETA_HIGH = 80.0
THETA_LOW = 60.0
THRESHOLD_STATUS = "pilot-locked; verify before the main experiment"
PRETEST_IDS = tuple(f"PRE{number:02d}" for number in range(1, 13))
POSTTEST_IDS = tuple(f"POST{number:02d}" for number in range(1, 13))


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    """Central research parameters and pilot-calibration decision boundaries."""

    alpha: float = 0.4
    initial_competence: float = 0.5
    progression_threshold: float = 0.80
    consecutive_safe_required: int = 2
    repeated_error_count: int = 2
    repeated_error_window: int = 3
    theta_high: float = THETA_HIGH
    theta_low: float = THETA_LOW
    threshold_status: str = THRESHOLD_STATUS
    training_attempts: int = 12
    pretest_scenario_ids: tuple[str, ...] = PRETEST_IDS
    posttest_scenario_ids: tuple[str, ...] = POSTTEST_IDS
    version: str = "3.0-protocol"

    def __post_init__(self) -> None:
        """Reject invalid settings before they affect participant outcomes."""
        for name in ("alpha", "initial_competence", "progression_threshold"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if not 0 <= self.theta_high <= 100:
            raise ValueError("theta_high must be between 0 and 100")
        if not 0 <= self.theta_low <= self.theta_high:
            raise ValueError("theta_low must be between 0 and theta_high")
        if self.consecutive_safe_required < 1 or self.repeated_error_count < 1 or self.repeated_error_window < 1:
            raise ValueError("decision counts and window must be positive")
        if self.repeated_error_count > self.repeated_error_window:
            raise ValueError("repeated_error_count cannot exceed its window")
        if self.training_attempts < 1:
            raise ValueError("training_attempts must be positive")


DEFAULT_POLICY = PolicyConfig()
