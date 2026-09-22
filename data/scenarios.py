"""Validated scenario content and choices loaded from central JSON data.

The PPE and hazard lists used by the UI are sourced here; UI components must
not maintain independent answer keys or global option lists.
"""

import json
from dataclasses import dataclass, replace
from pathlib import Path

from data.catalog import HAZARD_CATALOG, PPE_CATALOG
from data.models import Scenario


@dataclass(frozen=True, slots=True)
class ScenarioContent:
    """Scored scenario plus participant-facing text and selectable candidates."""

    scenario: Scenario
    title: str
    location: str
    situation: str
    task: str
    candidate_ppe: tuple[str, ...]
    candidate_hazards: tuple[str, ...]
    hazard_source: str
    domain_id: str = ""
    content_status: str = "EXPERT_REVIEWED_DOMAIN"
    phase: str | None = None


def _load_domains() -> tuple[ScenarioContent, ...]:
    """Load the six validated hazard-PPE ground-truth domains."""
    path = Path(__file__).resolve().parent / "scenarios.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    contents: list[ScenarioContent] = []
    for row in data["scenarios"]:
        required = frozenset(row["required_ppe"])
        critical = frozenset(row["critical_ppe"])
        hazards = frozenset(row["hazards"])
        ppe_options = tuple(row["candidate_ppe"])
        hazard_options = tuple(row["candidate_hazards"])
        if not 4 <= len(ppe_options) <= 6 or len(set(ppe_options)) != len(ppe_options):
            raise ValueError(f"{row['id']}: provide 4–6 distinct PPE candidates")
        if not 4 <= len(hazard_options) <= 6 or len(set(hazard_options)) != len(hazard_options):
            raise ValueError(f"{row['id']}: provide 4–6 distinct hazard candidates")
        if not required <= set(ppe_options) or not hazards <= set(hazard_options):
            raise ValueError(f"{row['id']}: required PPE and true hazards must be selectable")
        if not set(ppe_options) <= PPE_CATALOG.keys() or not set(hazard_options) <= HAZARD_CATALOG.keys():
            raise ValueError(f"{row['id']}: candidate identifier is missing from its catalog")
        if any(not PPE_CATALOG[item].scored for item in required):
            raise ValueError(f"{row['id']}: contextual PPE cannot enter PDSS ground truth")
        if row["id"] == "S3" and "face_shield" in required:
            raise ValueError("S3 face shield is a review category, not scored truth")
        if row["id"] == "S6" and "high_visibility_vest" in required:
            raise ValueError("S6 high-visibility vest is a review category, not scored truth")
        scenario = Scenario(
            id=row["id"], hazard_id=row["hazard_id"], required_ppe=required,
            critical_ppe=critical, expected_hazards=hazards,
            control_order=row["control_order"],
            reinforcement_for=frozenset(row["reinforcement_for"]),
            version=data["version"], complexity=row["complexity"],
            risk_priorities=tuple((key, float(value)) for key, value in row["risk_priorities"].items()),
            risk_priority_source=row["risk_priority_source"],
            expert_validation_status=row["expert_validation_status"],
            primary_expert_panel_n=data["primary_expert_panel_n"],
            followup_expert_panel_n=data["s5_followup_panel_n"] if row["id"] == "S5" else None,
        )
        contents.append(ScenarioContent(
            scenario, row["title"], row["location"], row["situation"], row["task"],
            ppe_options, hazard_options, row["hazard_source"], row["id"],
        ))
    if len({item.scenario.id for item in contents}) != len(contents):
        raise ValueError("scenario IDs must be unique")
    return tuple(contents)


DOMAIN_SCENARIOS = _load_domains()
_DOMAINS = {item.scenario.id: item for item in DOMAIN_SCENARIOS}


def _load_variants(filename: str, key: str, status: str) -> tuple[ScenarioContent, ...]:
    """Load narrative variants while inheriting domain truth and candidates."""
    path = Path(__file__).resolve().parent / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    variants: list[ScenarioContent] = []
    for position, row in enumerate(data[key]):
        domain = _DOMAINS[row["domain_id"]]
        card = replace(
            domain,
            scenario=replace(domain.scenario, id=row["id"],
                             control_order=row.get("control_order", position), version=data["version"]),
            title=row["title"], location=row["location"],
            situation=row["situation"], task=row["task"],
            content_status=status, phase=row.get("phase"),
        )
        variants.append(card)
    if len({item.scenario.id for item in variants}) != len(variants):
        raise ValueError(f"{filename} contains duplicate IDs")
    return tuple(variants)


SCENARIOS = _load_variants("training_cards.json", "cards", "PROTOCOL_DERIVED_TRAINING_VARIANT")
ASSESSMENTS = _load_variants("assessment_items.json", "items", "PROTOCOL_DEFINED_EQUIVALENT")
_BY_ID = {item.scenario.id: item for item in (*DOMAIN_SCENARIOS, *SCENARIOS, *ASSESSMENTS)}
_ASSESSMENT_BY_ID = {item.scenario.id: item for item in ASSESSMENTS}

_EXPECTED_TRAINING_ORDER = tuple(f"S{number}{variant}" for variant in "AB" for number in range(1, 7))
if len(SCENARIOS) != 12 or tuple(item.scenario.id for item in SCENARIOS) != _EXPECTED_TRAINING_ORDER:
    raise ValueError("training bank must contain S1A–S6A followed by S1B–S6B")
_EXPECTED_ASSESSMENT_IDS = tuple(f"{phase}{number:02d}" for phase in ("PRE", "POST") for number in range(1, 13))
if len(ASSESSMENTS) != 24 or tuple(item.scenario.id for item in ASSESSMENTS) != _EXPECTED_ASSESSMENT_IDS:
    raise ValueError("assessment bank must contain PRE01–12 and POST01–12")
for item in ASSESSMENTS:
    item_number = int(item.scenario.id[-2:])
    expected_domain = f"S{(item_number - 1) // 2 + 1}"
    if item.domain_id != expected_domain or item.phase != item.scenario.id[:-2]:
        raise ValueError(f"{item.scenario.id}: assessment phase/domain mapping is invalid")
for number in range(1, 13):
    pre = _ASSESSMENT_BY_ID[f"PRE{number:02d}"]
    post = _ASSESSMENT_BY_ID[f"POST{number:02d}"]
    if pre.situation == post.situation:
        raise ValueError(f"assessment item {number}: post wording must differ from pre")


def scenario_by_id(scenario_id: str) -> ScenarioContent:
    """Find a domain or training card by its stable identifier."""
    return _BY_ID[scenario_id]


def assessment_by_id(item_id: str) -> ScenarioContent:
    """Find a protocol-defined blinded assessment item."""
    return _ASSESSMENT_BY_ID[item_id]
