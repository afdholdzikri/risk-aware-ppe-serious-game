"""Research-specification scoring and adaptive-rule regression tests."""

import pytest

from app.config import THETA_HIGH, THETA_LOW, THRESHOLD_STATUS, PolicyConfig
from data.models import Condition, Decision, Exposure, Scenario
from data.scenarios import SCENARIOS, scenario_by_id
from engine.competence import can_progress, initial_state, update_competence
from engine.scoring import hazard_recognition_accuracy, score_decision
from engine.selection import repeated_errors, select_scenario


def s1() -> Scenario:
    """Use the actual validated S1 record for numeric regression tests."""
    return scenario_by_id("S1").scenario


def s5() -> Scenario:
    """Use the actual validated S5 record for numeric regression tests."""
    return scenario_by_id("S5").scenario


def test_s1_pdss_coverage_pda_and_critical_rule():
    item = s1()
    all_selected = score_decision(item, Decision("S1", item.required_ppe, item.expected_hazards))
    assert all_selected.pdss == 100
    assert all_selected.required_ppe_coverage == 100
    assert all_selected.pda == 1
    assert not all_selected.critical_error
    vest_omitted = score_decision(item, Decision("S1", item.required_ppe - {"high_visibility_vest"}, frozenset()))
    assert vest_omitted.pdss == pytest.approx(71.4286, abs=0.0001)
    assert vest_omitted.required_ppe_coverage == pytest.approx(66.6667, abs=0.0001)
    assert vest_omitted.pda == 0
    assert not vest_omitted.critical_error
    assert vest_omitted.decision_state == "RISKY"
    helmet_omitted = score_decision(item, Decision("S1", item.required_ppe - {"safety_helmet"}, frozenset()))
    assert helmet_omitted.pdss == pytest.approx(64.2857, abs=0.0001)
    assert helmet_omitted.required_ppe_coverage == pytest.approx(66.6667, abs=0.0001)
    assert helmet_omitted.pda == 0
    assert helmet_omitted.critical_error
    assert helmet_omitted.decision_state == "UNSAFE"


def test_s5_critical_override_and_pdss():
    item = s5()
    result = score_decision(item, Decision("S5", item.required_ppe - {"eye_face_protection"}, frozenset()))
    assert result.pdss == pytest.approx(78.9474, abs=0.0001)
    assert result.critical_error
    assert result.decision_state == "UNSAFE"


def test_overselection_does_not_reduce_pdss():
    item = s1()
    result = score_decision(item, Decision("S1", item.required_ppe | {"extra"}, item.expected_hazards))
    assert result.pdss == 100
    assert result.required_ppe_coverage == 100
    assert result.pda == 0
    assert result.os == 1 and result.extra_ppe == frozenset({"extra"})


def test_hazard_recognition_prevents_select_all():
    assert hazard_recognition_accuracy(frozenset({"A", "B", "C"}), frozenset({"A", "C", "D"})) == 50


def test_competence_and_safe_streak():
    state = initial_state()
    assert state.value == 0.5
    state = update_competence(state, 100, "SAFE")
    assert state.value == pytest.approx(0.7)
    assert not can_progress(state)
    state = update_competence(state, 100, "SAFE")
    assert state.value == pytest.approx(0.82)
    assert state.consecutive_safe == 2 and can_progress(state)
    state = update_competence(state, 50, "RISKY")
    assert state.value == pytest.approx(0.692)
    assert state.consecutive_safe == 0


def test_repeated_error_window():
    history = [
        Exposure("a", "site", False, frozenset({"helmet"})),
        Exposure("b", "other", False, frozenset({"x"})),
        Exposure("c", "site", True, frozenset()),
        Exposure("d", "site", False, frozenset({"helmet"})),
    ]
    assert ("site", "helmet") in repeated_errors(history)
    history.append(Exposure("e", "site", True, frozenset()))
    assert ("site", "helmet") not in repeated_errors(history)


def test_control_is_fixed_twelve_attempts():
    items = [s1(), s5()]
    history: list[Exposure] = []
    selected = []
    for _ in range(12):
        item = select_scenario(items, Condition.CONTROL, history)
        selected.append(item.id)
        history.append(Exposure(item.id, item.hazard_id, True, frozenset()))
    assert selected == ["S1", "S5"] * 6
    assert select_scenario(items, Condition.CONTROL, history) is None


def test_adaptive_critical_priority_avoids_exact_repeat():
    base = s1()
    remedial = Scenario(
        "S1-R", base.hazard_id, base.required_ppe, base.critical_ppe,
        base.expected_hazards, 2, frozenset({"safety_helmet"}),
        risk_priorities=base.risk_priorities,
    )
    history = [Exposure("S1", base.hazard_id, False, frozenset({"safety_helmet"}), "UNSAFE", True, 1)]
    assert select_scenario([base, remedial], Condition.ADAPTIVE, history) == remedial


def test_policy_and_scenario_validation():
    with pytest.raises(ValueError):
        PolicyConfig(theta_low=90)
    with pytest.raises(ValueError):
        Scenario("x", "h", frozenset({"a"}), frozenset(), frozenset(), 0)


def test_pilot_locked_threshold_boundaries_and_critical_override():
    assert THETA_HIGH == 80
    assert THETA_LOW == 60
    assert THRESHOLD_STATUS == "pilot-locked; verify before the main experiment"

    def state_for_omission(omitted_priority: int, critical: bool = False) -> str:
        item = Scenario(
            "BOUNDARY", "test", frozenset({"omitted", "selected"}),
            frozenset({"omitted"}) if critical else frozenset(), frozenset(), 0,
            risk_priorities=(("omitted", omitted_priority),
                             ("selected", 10000 - omitted_priority)),
        )
        return score_decision(item, Decision("BOUNDARY", frozenset({"selected"}), frozenset())).decision_state

    assert state_for_omission(2000) == "SAFE"       # PDSS 80
    assert state_for_omission(2001) == "RISKY"      # PDSS 79.99
    assert state_for_omission(4000) == "RISKY"      # PDSS 60
    assert state_for_omission(4001) == "UNSAFE"     # PDSS 59.99
    assert state_for_omission(2000, critical=True) == "UNSAFE"


def test_adaptive_switches_to_equivalent_variant_after_critical_omission():
    first = scenario_by_id("S1A").scenario
    history = [Exposure("S1A", first.hazard_id, False,
                        frozenset({"safety_helmet"}), "UNSAFE", True, first.complexity)]
    selected = select_scenario([item.scenario for item in SCENARIOS], Condition.ADAPTIVE, history)
    assert selected.id == "S1B"
