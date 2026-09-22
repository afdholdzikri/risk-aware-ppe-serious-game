"""Validated catalog completeness and scenario option coverage."""

import pytest

from app.config import DEFAULT_POLICY
from data.catalog import HAZARD_CATALOG, PPE_CATALOG
from data.scenarios import ASSESSMENTS, DOMAIN_SCENARIOS, SCENARIOS, assessment_by_id, scenario_by_id
from data.models import Decision
from engine.scoring import score_decision


EXPECTED_REQUIRED = {
    "S1": {"safety_helmet", "safety_footwear", "high_visibility_vest"},
    "S2": {"eye_protection", "face_shield", "protective_gloves", "safety_footwear"},
    "S3": {"chemical_goggles", "chemical_resistant_gloves", "safety_footwear"},
    "S4": {"hearing_protection", "high_visibility_vest", "safety_footwear"},
    "S5": {"electrical_protective_gloves", "safety_footwear", "eye_face_protection", "safety_helmet"},
    "S6": {"safety_helmet", "eye_protection", "safety_footwear", "hearing_protection"},
}

EXPECTED_CRITICAL = {
    "S1": {"safety_helmet", "safety_footwear"},
    "S2": {"eye_protection", "safety_footwear"},
    "S3": {"chemical_goggles"},
    "S4": set(),
    "S5": EXPECTED_REQUIRED["S5"],
    "S6": {"safety_helmet", "eye_protection", "safety_footwear"},
}

EXPECTED_PRIORITIES = {
    "S1": {"safety_helmet": 5, "safety_footwear": 5, "high_visibility_vest": 4},
    "S2": {"eye_protection": 5, "face_shield": 4, "protective_gloves": 4, "safety_footwear": 4},
    "S3": {"chemical_goggles": 5, "chemical_resistant_gloves": 5, "safety_footwear": 4},
    "S4": {"hearing_protection": 5, "high_visibility_vest": 5, "safety_footwear": 4},
    "S5": {"electrical_protective_gloves": 5, "safety_footwear": 5, "eye_face_protection": 4, "safety_helmet": 5},
    "S6": {"safety_helmet": 5, "eye_protection": 5, "safety_footwear": 5, "hearing_protection": 5},
}

EXPECTED_HAZARDS = {
    "S1": {"falling_objects", "foot_impact", "moving_equipment"},
    "S2": {"flying_particles", "sparks_hot_particles", "sharp_object_contact"},
    "S3": {"chemical_splash", "chemical_skin_contact"},
    "S4": {"elevated_noise", "moving_equipment"},
    "S5": {"electrical_contact", "electrical_fault_spark"},
    "S6": {"falling_objects", "airborne_particles", "elevated_noise", "moving_equipment"},
}


def test_master_catalogs_have_exact_requested_identifiers():
    assert set(PPE_CATALOG) == {
        "safety_helmet", "safety_footwear", "high_visibility_vest", "eye_protection",
        "face_shield", "protective_gloves", "chemical_goggles", "chemical_resistant_gloves",
        "hearing_protection", "electrical_protective_gloves", "eye_face_protection",
        "chemical_resistant_apron", "arc_rated_flame_resistant_clothing",
    }
    assert set(HAZARD_CATALOG) == {
        "falling_objects", "foot_impact", "moving_equipment", "flying_particles",
        "sparks_hot_particles", "sharp_object_contact", "chemical_splash",
        "chemical_skin_contact", "elevated_noise", "electrical_contact",
        "electrical_fault_spark", "airborne_particles",
    }
    assert not PPE_CATALOG["chemical_resistant_apron"].scored
    assert not PPE_CATALOG["arc_rated_flame_resistant_clothing"].scored
    assert "insulated_tools" not in PPE_CATALOG


@pytest.mark.parametrize("scenario_id", list(EXPECTED_REQUIRED))
def test_final_scenario_truth_and_choices(scenario_id):
    content = scenario_by_id(scenario_id)
    scenario = content.scenario
    assert set(scenario.required_ppe) == EXPECTED_REQUIRED[scenario_id]
    assert set(scenario.critical_ppe) == EXPECTED_CRITICAL[scenario_id]
    assert dict(scenario.risk_priorities) == EXPECTED_PRIORITIES[scenario_id]
    assert set(scenario.expected_hazards) == EXPECTED_HAZARDS[scenario_id]
    assert scenario.required_ppe <= set(content.candidate_ppe)
    assert scenario.expected_hazards <= set(content.candidate_hazards)
    assert 4 <= len(content.candidate_ppe) <= 6
    assert 4 <= len(content.candidate_hazards) <= 6
    assert set(content.candidate_ppe) - scenario.required_ppe
    assert set(content.candidate_hazards) - scenario.expected_hazards
    assert scenario.expert_validation_status == "final"
    assert scenario.risk_priority_source == "EXPERT_MEDIAN"
    assert scenario.primary_expert_panel_n == 13
    assert content.hazard_source == "SCENARIO_DEFINED_EXPERT_REVIEWED"
    result = score_decision(scenario, Decision(scenario_id, scenario.required_ppe, scenario.expected_hazards))
    assert result.pdss == 100 and result.hra == 100


def test_specific_required_choices_and_provenance():
    assert "safety_footwear" in scenario_by_id("S3").candidate_ppe
    assert EXPECTED_REQUIRED["S5"] <= set(scenario_by_id("S5").candidate_ppe)
    assert "hearing_protection" in scenario_by_id("S6").candidate_ppe
    assert "face_shield" not in scenario_by_id("S3").scenario.required_ppe
    assert "high_visibility_vest" not in scenario_by_id("S6").scenario.required_ppe
    assert scenario_by_id("S5").scenario.followup_expert_panel_n == 13
    assert all(item.scenario.followup_expert_panel_n is None for item in DOMAIN_SCENARIOS if item.scenario.id != "S5")


def test_training_bank_has_exact_protocol_order_and_pair_truth():
    expected_order = [f"S{number}{variant}" for variant in "AB" for number in range(1, 7)]
    assert [card.scenario.id for card in SCENARIOS] == expected_order
    for number in range(1, 7):
        domain = scenario_by_id(f"S{number}")
        a = scenario_by_id(f"S{number}A")
        b = scenario_by_id(f"S{number}B")
        assert a.situation != b.situation
        for variant in (a, b):
            assert variant.domain_id == domain.scenario.id
            assert variant.scenario.required_ppe == domain.scenario.required_ppe
            assert variant.scenario.critical_ppe == domain.scenario.critical_ppe
            assert variant.scenario.risk_priorities == domain.scenario.risk_priorities
            assert variant.scenario.expected_hazards == domain.scenario.expected_hazards
            assert variant.candidate_ppe == domain.candidate_ppe
            assert variant.candidate_hazards == domain.candidate_hazards


def test_twelve_pre_and_post_items_inherit_domain_truth():
    assert len(ASSESSMENTS) == 24
    assert DEFAULT_POLICY.pretest_scenario_ids == tuple(f"PRE{number:02d}" for number in range(1, 13))
    assert DEFAULT_POLICY.posttest_scenario_ids == tuple(f"POST{number:02d}" for number in range(1, 13))
    assert [item.scenario.id for item in ASSESSMENTS] == [
        f"{phase}{number:02d}" for phase in ("PRE", "POST") for number in range(1, 13)
    ]
    for number in range(1, 13):
        domain_id = f"S{(number - 1) // 2 + 1}"
        domain = scenario_by_id(domain_id)
        pre = assessment_by_id(f"PRE{number:02d}")
        post = assessment_by_id(f"POST{number:02d}")
        assert pre.situation != post.situation
        for item in (pre, post):
            assert item.domain_id == domain_id
            assert item.content_status == "PROTOCOL_DEFINED_EQUIVALENT"
            assert item.scenario.required_ppe == domain.scenario.required_ppe
            assert item.scenario.critical_ppe == domain.scenario.critical_ppe
            assert item.scenario.risk_priorities == domain.scenario.risk_priorities
            assert item.scenario.expected_hazards == domain.scenario.expected_hazards
            assert item.scenario.required_ppe <= set(item.candidate_ppe)
            assert item.scenario.expected_hazards <= set(item.candidate_hazards)
