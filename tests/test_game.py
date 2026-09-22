"""Integration tests for relational research logging and game transitions."""

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.schema import CreateTable

from app.game import (
    GameSession, next_scenario, present_scenario, start_session,
    submit_assessment_decision, submit_decision,
)
from datetime import datetime, timezone
from data.scenarios import ASSESSMENTS, SCENARIOS
from data.models import Condition
from database.log import (
    append_assessment, assessment_logs, create_log_engine, participants,
    sessions, training_logs, default_database_url,
)


def test_adaptive_submission_persists_full_research_record(tmp_path):
    engine = create_log_engine(f"sqlite:///{(tmp_path / 'study.db').as_posix()}")
    assert {"participants", "sessions", "assessment_logs", "training_logs"} <= set(inspect(engine).get_table_names())
    game = GameSession("P-104", Condition.ADAPTIVE)
    start_session(game, engine)
    first = next_scenario(game)
    assert first is not None
    present_scenario(game, first)
    result = submit_decision(game, set(first.scenario.required_ppe),
                             set(first.scenario.expected_hazards), engine)
    assert result.safe
    assert game.competence[first.scenario.hazard_id].value == 0.7
    with engine.connect() as connection:
        participant = connection.execute(select(participants)).mappings().one()
        session = connection.execute(select(sessions)).mappings().one()
        row = connection.execute(select(training_logs)).mappings().one()
    assert participant["participant_code"] == "P-104"
    assert participant["participant_id"] == row["participant_id"] == session["participant_id"]
    assert session["status"] == "ACTIVE"
    assert row["group"] == "ADAPTIVE"
    assert row["attempt"] == 1
    assert row["scenario_id"] == first.scenario.id
    assert row["complexity"] == 1
    assert row["selected_ppe"] == sorted(first.scenario.required_ppe)
    assert row["required_ppe"] == sorted(first.scenario.required_ppe)
    assert row["missing_ppe"] == []
    assert row["pdss"] == 100.0 and row["decision_state"] == "SAFE"
    assert row["selected_hazards"] == sorted(first.scenario.expected_hazards)
    assert row["required_ppe_coverage"] == 100.0
    assert row["hra"] == 100.0 and row["pda"] == 1
    assert row["extra_ppe"] == [] and row["os"] == 0
    assert row["safe_streak"] == 1
    assert row["risk_priority_source"] == "EXPERT_MEDIAN"
    assert row["expert_validation_status"] == "final"
    assert row["primary_expert_panel_n"] == 13
    assert row["hazard_source"] == "SCENARIO_DEFINED_EXPERT_REVIEWED"
    assert row["critical_error"] is False
    assert row["decision_time"] >= 0
    assert row["competence_before"] == 0.5 and row["competence_after"] == 0.7
    assert row["remedial_flag"] is False and row["target_error"] is None
    assert row["next_scenario"] == next_scenario(game).scenario.id
    assert row["timestamp"] is not None


def test_control_completes_and_assessment_links_to_session(tmp_path):
    engine = create_log_engine(f"sqlite:///{(tmp_path / 'study.db').as_posix()}")
    game = GameSession("P-105", Condition.CONTROL)
    start_session(game, engine)
    seen = []
    while chosen := next_scenario(game):
        seen.append(chosen.scenario.id)
        present_scenario(game, chosen)
        submit_decision(game, set(), set(), engine)
    assert seen == [f"S{number}{variant}" for variant in "AB" for number in range(1, 7)]
    append_assessment(engine, game.participant_id, game.session_id, "POST", 0.75,
                      {"scenario_id": "POST01", "items": 4}, close_session=True)
    with engine.connect() as connection:
        rows = connection.execute(select(training_logs).order_by(training_logs.c.attempt)).mappings().all()
        session = connection.execute(select(sessions)).mappings().one()
        assessment = connection.execute(select(assessment_logs)).mappings().one()
    assert len(rows) == 12
    assert rows[-1]["next_scenario"] is None
    assert rows[0]["critical_error"] is True
    assert session["status"] == "COMPLETED" and session["completed_at"] is not None
    assert assessment["session_id"] == game.session_id and assessment["score"] == 0.75


def test_adaptive_also_runs_exactly_twelve_attempts(tmp_path):
    engine = create_log_engine(f"sqlite:///{(tmp_path / 'adaptive.db').as_posix()}")
    game = GameSession("P-ADAPT-12", Condition.ADAPTIVE)
    start_session(game, engine)
    for _ in range(12):
        chosen = next_scenario(game)
        assert chosen is not None
        present_scenario(game, chosen)
        submit_decision(game, set(chosen.scenario.required_ppe),
                        set(chosen.scenario.expected_hazards), engine)
    assert next_scenario(game) is None
    with engine.connect() as connection:
        rows = connection.execute(select(training_logs)).all()
    assert len(rows) == 12


def test_participant_group_is_stable_across_sessions(tmp_path):
    engine = create_log_engine(f"sqlite:///{(tmp_path / 'study.db').as_posix()}")
    first = GameSession("P-106", Condition.CONTROL)
    start_session(first, engine)
    repeat = GameSession("P-106", Condition.CONTROL)
    start_session(repeat, engine)
    assert first.participant_id == repeat.participant_id
    with pytest.raises(ValueError, match="another group"):
        start_session(GameSession("P-106", Condition.ADAPTIVE), engine)
    with engine.connect() as connection:
        assert len(connection.execute(select(participants)).all()) == 1
        assert len(connection.execute(select(sessions)).all()) == 2


def test_repeated_error_marks_targeted_remedial_exposure(tmp_path):
    engine = create_log_engine(f"sqlite:///{(tmp_path / 'study.db').as_posix()}")
    game = GameSession("P-107", Condition.ADAPTIVE)
    start_session(game, engine)
    for _ in range(3):
        chosen = next_scenario(game)
        present_scenario(game, chosen)
        submit_decision(game, set(), set(), engine)
    chosen = next_scenario(game)
    assert chosen is not None
    present_scenario(game, chosen)
    assert game.remedial_flag and game.target_error is not None
    submit_decision(game, set(), set(), engine)
    with engine.connect() as connection:
        row = connection.execute(select(training_logs).where(training_logs.c.attempt == 4)).mappings().one()
    assert row["remedial_flag"] is True
    assert row["target_error"] in {
        "site_movement:safety_helmet", "site_movement:safety_footwear",
        "site_movement:high_visibility_vest",
    }


def test_database_url_environment_precedes_streamlit_secrets(monkeypatch):
    import streamlit as st

    monkeypatch.setattr(st, "secrets", {"DATABASE_URL": "sqlite:///secret.db"})
    monkeypatch.setenv("DATABASE_URL", "sqlite:///environment.db")
    assert default_database_url() == "sqlite:///environment.db"
    monkeypatch.delenv("DATABASE_URL")
    assert default_database_url() == "sqlite:///secret.db"


def test_research_tables_compile_for_postgresql():
    for table in (participants, sessions, assessment_logs, training_logs):
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert f"CREATE TABLE {table.name}" in ddl


def test_training_rerun_is_idempotent(tmp_path):
    engine = create_log_engine(f"sqlite:///{(tmp_path / 'study.db').as_posix()}")
    game = GameSession("P-108", Condition.CONTROL)
    start_session(game, engine)
    chosen = next_scenario(game)
    present_scenario(game, chosen)
    duplicate = GameSession(game.participant_code, game.condition, game.session_id,
                            participant_id=game.participant_id)
    present_scenario(duplicate, chosen)
    submit_decision(game, set(), set(), engine)
    submit_decision(duplicate, set(), set(), engine)
    with engine.connect() as connection:
        assert len(connection.execute(select(training_logs)).all()) == 1


def test_assessment_scores_are_stored_without_training_feedback(tmp_path):
    engine = create_log_engine(f"sqlite:///{(tmp_path / 'study.db').as_posix()}")
    game = GameSession("P-109", Condition.ADAPTIVE)
    start_session(game, engine)
    content = ASSESSMENTS[0]
    returned = submit_assessment_decision(
        game, content, set(content.scenario.required_ppe),
        set(content.scenario.expected_hazards), engine, "PRE", datetime.now(timezone.utc),
    )
    submit_assessment_decision(
        game, content, set(content.scenario.required_ppe),
        set(content.scenario.expected_hazards), engine, "PRE", datetime.now(timezone.utc),
    )
    assert returned is None
    assert game.latest_feedback is None and game.latest_result is None
    assert not game.exposures
    with engine.connect() as connection:
        row = connection.execute(select(assessment_logs)).mappings().one()
    assert row["phase"] == "PRE"
    assert row["score"] == 100.0
    assert row["details"]["pdss"] == 100.0
    assert row["details"]["os"] == 0
    assert row["details"]["content_status"] == "PROTOCOL_DEFINED_EQUIVALENT"
    assert {"hra", "pda", "required_ppe_coverage", "critical_error", "decision_time",
            "selected_hazards", "selected_ppe"} <= row["details"].keys()


def test_twelve_pre_and_twelve_post_assessments_are_persisted(tmp_path):
    engine = create_log_engine(f"sqlite:///{(tmp_path / 'assessments.db').as_posix()}")
    game = GameSession("P-24-ASSESS", Condition.CONTROL)
    start_session(game, engine)
    for index, content in enumerate(ASSESSMENTS):
        submit_assessment_decision(
            game, content, set(content.scenario.required_ppe),
            set(content.scenario.expected_hazards), engine, content.phase,
            datetime.now(timezone.utc), close_session=index == len(ASSESSMENTS) - 1,
        )
    with engine.connect() as connection:
        rows = connection.execute(select(assessment_logs)).mappings().all()
        session = connection.execute(select(sessions)).mappings().one()
    assert len(rows) == 24
    assert sum(row["phase"] == "PRE" for row in rows) == 12
    assert sum(row["phase"] == "POST" for row in rows) == 12
    assert {row["details"]["scenario_id"] for row in rows} == {
        item.scenario.id for item in ASSESSMENTS
    }
    assert session["status"] == "COMPLETED"


def test_legacy_training_table_gets_additive_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    old_engine = create_engine(url)
    with old_engine.begin() as connection:
        connection.execute(text("CREATE TABLE training_logs (training_log_id INTEGER PRIMARY KEY, session_id VARCHAR(36), attempt INTEGER)"))
    old_engine.dispose()
    engine = create_log_engine(url)
    columns = {column["name"] for column in inspect(engine).get_columns("training_logs")}
    assert {"selected_hazards", "extra_ppe", "hra", "required_ppe_coverage", "pda",
            "safe_streak", "reinforcement_focus"} <= columns


def test_legacy_assessment_table_gets_item_key(tmp_path):
    url = f"sqlite:///{(tmp_path / 'legacy-assess.db').as_posix()}"
    old_engine = create_engine(url)
    with old_engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE assessment_logs (assessment_id INTEGER PRIMARY KEY, "
            "session_id VARCHAR(36), phase VARCHAR(32), details JSON)"
        ))
    old_engine.dispose()
    engine = create_log_engine(url)
    assert "item_id" in {column["name"] for column in inspect(engine).get_columns("assessment_logs")}
    assert "uq_assessment_session_phase_item" in {
        index["name"] for index in inspect(engine).get_indexes("assessment_logs")
    }
