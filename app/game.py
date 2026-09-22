"""Python-only orchestration of scoring, feedback, selection, and logging."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.engine import Engine

from app.config import DEFAULT_POLICY, PolicyConfig
from data.models import Condition, Decision, Exposure
from data.scenarios import SCENARIOS, ScenarioContent, scenario_by_id
from database.log import append_assessment, append_training_decision, register_session
from engine.competence import CompetenceState, can_progress, initial_state, update_competence
from engine.feedback import feedback
from engine.scoring import ScoreResult, score_decision
from engine.selection import repeated_errors, select_scenario


@dataclass(slots=True)
class GameSession:
    """Temporary in-memory state for one browser session."""

    participant_code: str
    condition: Condition
    session_id: str = field(default_factory=lambda: str(uuid4()))
    participant_id: str | None = None
    exposures: list[Exposure] = field(default_factory=list)
    competence: dict[str, CompetenceState] = field(default_factory=dict)
    current_scenario_id: str | None = None
    scenario_started_at: datetime | None = None
    remedial_flag: bool = False
    target_error: str | None = None
    latest_result: ScoreResult | None = None
    latest_feedback: str | None = None
    latest_reinforcement_focus: str | None = None
    assessment_phase: str | None = None
    assessment_index: int = 0
    assessment_started_at: datetime | None = None


def _select_next(
    condition: Condition, exposures: list[Exposure], competence: dict[str, CompetenceState],
    policy: PolicyConfig,
) -> ScenarioContent | None:
    """Pure selection helper used before display and before log insertion."""
    if len(exposures) >= policy.training_attempts:
        return None
    chosen = select_scenario(
        [item.scenario for item in SCENARIOS], condition,
        exposures, competence, policy,
    )
    return scenario_by_id(chosen.id) if chosen else None


def next_scenario(game: GameSession, policy: PolicyConfig = DEFAULT_POLICY) -> ScenarioContent | None:
    """Select the next exposure, or end when the condition's stop rule is met."""
    return _select_next(game.condition, game.exposures, game.competence, policy)


def start_session(game: GameSession, engine: Engine) -> None:
    """Persist participant identity and session before the first exposure."""
    if game.participant_id is not None:
        raise ValueError("session already started")
    game.participant_id = register_session(engine, game.participant_code, game.condition.value, game.session_id)


def present_scenario(
    game: GameSession, content: ScenarioContent, policy: PolicyConfig = DEFAULT_POLICY,
) -> None:
    """Record presentation time and whether selection targets a repeated error."""
    game.current_scenario_id = content.scenario.id
    game.scenario_started_at = datetime.now(timezone.utc)
    errors = sorted(
        ppe for hazard, ppe in repeated_errors(game.exposures, policy)
        if hazard == content.scenario.hazard_id and ppe in content.scenario.reinforcement_for
    ) if game.condition == Condition.ADAPTIVE else []
    last = game.exposures[-1] if game.exposures else None
    if not errors and last and last.hazard_id == content.scenario.hazard_id and game.condition == Condition.ADAPTIVE:
        errors = sorted(last.omitted_ppe & content.scenario.reinforcement_for)
    game.remedial_flag = bool(errors) and bool(last and (last.critical_error or last.decision_state == "UNSAFE"))
    game.target_error = f"{content.scenario.hazard_id}:{errors[0]}" if errors else None


def submit_decision(
    game: GameSession, selected_ppe: set[str], identified_hazards: set[str],
    engine: Engine, policy: PolicyConfig = DEFAULT_POLICY,
) -> ScoreResult:
    """Score, persist, and then apply a single participant decision.

    State advances only after the database transaction succeeds, preventing a
    browser session from claiming an interaction that was not saved.
    """
    if game.current_scenario_id is None:
        raise ValueError("no active scenario")
    if game.participant_id is None:
        raise ValueError("session must be registered before a decision")
    if game.scenario_started_at is None:
        raise ValueError("scenario must be presented before a decision")
    content = scenario_by_id(game.current_scenario_id)
    scenario = content.scenario
    decision = Decision(scenario.id, frozenset(selected_ppe), frozenset(identified_hazards))
    result = score_decision(scenario, decision, policy)
    prior = game.competence.get(scenario.hazard_id, initial_state(policy))
    updated = update_competence(prior, result.pdss, result.decision_state, policy)
    future_exposures = [*game.exposures, Exposure(
        scenario.id, scenario.hazard_id, result.safe, result.omitted_ppe,
        result.decision_state, result.critical_error, scenario.complexity,
    )]
    future_competence = {**game.competence, scenario.hazard_id: updated}
    following = _select_next(game.condition, future_exposures, future_competence, policy)
    timestamp = datetime.now(timezone.utc)
    decision_seconds = max(0.0, (timestamp - game.scenario_started_at).total_seconds())
    focus_code = game.target_error or (
        f"{scenario.hazard_id}:{sorted(result.omitted_ppe)[0]}" if result.omitted_ppe else None
    )
    append_training_decision(engine, {
        "participant_id": game.participant_id,
        "session_id": game.session_id,
        "group": game.condition.value,
        "attempt": len(game.exposures) + 1,
        "scenario_id": scenario.id,
        "domain_id": content.domain_id,
        "content_status": content.content_status,
        "scenario_version": scenario.version,
        "policy_version": policy.version,
        "complexity": scenario.complexity,
        "selected_ppe": sorted(decision.selected_ppe),
        "required_ppe": sorted(scenario.required_ppe),
        "missing_ppe": sorted(result.omitted_ppe),
        "extra_ppe": sorted(result.extra_ppe),
        "selected_hazards": sorted(decision.identified_hazards),
        "identified_hazards": sorted(decision.identified_hazards),
        "pdss": result.pdss,
        "ppe_accuracy": result.required_ppe_coverage,
        "hazard_accuracy": result.hra,
        "hra": result.hra,
        "required_ppe_coverage": result.required_ppe_coverage,
        "pda": result.pda,
        "os": result.os,
        "decision_state": result.decision_state,
        "critical_error": result.critical_error,
        "decision_time": decision_seconds,
        "competence_before": prior.value,
        "competence_after": updated.value,
        "safe_streak": updated.consecutive_safe,
        "remedial_flag": game.remedial_flag,
        "target_error": game.target_error,
        "reinforcement_focus": focus_code,
        "risk_priorities": [[ppe, value] for ppe, value in scenario.risk_priorities],
        "risk_priority_source": scenario.risk_priority_source,
        "expert_validation_status": scenario.expert_validation_status,
        "primary_expert_panel_n": scenario.primary_expert_panel_n,
        "followup_expert_panel_n": scenario.followup_expert_panel_n,
        "hazard_source": content.hazard_source,
        "next_scenario": following.scenario.id if following else None,
        "timestamp": timestamp,
    }, close_session=not policy.posttest_scenario_ids)
    game.competence[scenario.hazard_id] = updated
    game.exposures = future_exposures
    game.latest_result = result
    game.latest_feedback = feedback(game.condition, result)
    game.latest_reinforcement_focus = focus_code.replace(":", " → ") if focus_code else None
    game.current_scenario_id = None
    game.scenario_started_at = None
    game.remedial_flag = False
    game.target_error = None
    return result


def submit_assessment_decision(
    game: GameSession, content: ScenarioContent, selected_ppe: set[str],
    identified_hazards: set[str], engine: Engine, phase: str,
    started_at: datetime, close_session: bool = False,
    policy: PolicyConfig = DEFAULT_POLICY,
) -> None:
    """Score and store a pre/post item without exposing feedback or competence.

    The assessment record retains research variables, while the function
    deliberately returns no score and does not alter training state.
    """
    if phase not in {"PRE", "POST"} or game.participant_id is None:
        raise ValueError("invalid assessment phase or unregistered session")
    scenario = content.scenario
    decision = Decision(scenario.id, frozenset(selected_ppe), frozenset(identified_hazards))
    result = score_decision(scenario, decision, policy)
    duration = max(0.0, (datetime.now(timezone.utc) - started_at).total_seconds())
    append_assessment(engine, game.participant_id, game.session_id, phase, result.pdss, {
        "scenario_id": scenario.id,
        "domain_id": content.domain_id,
        "content_status": content.content_status,
        "scenario_version": scenario.version,
        "policy_version": policy.version,
        "selected_ppe": sorted(decision.selected_ppe),
        "selected_hazards": sorted(decision.identified_hazards),
        "required_ppe": sorted(scenario.required_ppe),
        "missing_ppe": sorted(result.omitted_ppe),
        "extra_ppe": sorted(result.extra_ppe),
        "os": result.os,
        "pdss": result.pdss,
        "required_ppe_coverage": result.required_ppe_coverage,
        "pda": result.pda,
        "hra": result.hra,
        "critical_error": result.critical_error,
        "decision_state": result.decision_state,
        "decision_time": duration,
        "ppe_parameter_validation_status": scenario.expert_validation_status,
        "primary_expert_panel_n": scenario.primary_expert_panel_n,
        "followup_expert_panel_n": scenario.followup_expert_panel_n,
        "hazard_source": content.hazard_source,
    }, close_session=close_session)
