"""Condition-specific feedback independent of UI rendering."""

from data.models import Condition
from engine.scoring import ScoreResult


def feedback(condition: Condition, result: ScoreResult) -> str:
    """Return standard or targeted textual feedback for one decision."""
    if condition == Condition.CONTROL:
        return "Safe decision." if result.safe else "Review your PPE selection and hazard assessment."
    if condition == Condition.ADAPTIVE:
        if result.missing_critical_ppe:
            return "Critical PPE missing: " + ", ".join(sorted(result.missing_critical_ppe))
        if result.omitted_ppe:
            return "Review required PPE: " + ", ".join(sorted(result.omitted_ppe))
        return "Safe decision." if result.safe else "Review hazard recognition and PPE choices."
    raise ValueError("unknown experimental condition")
