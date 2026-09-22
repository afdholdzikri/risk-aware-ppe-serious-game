"""Smoke test for the first playable browser flow."""

from streamlit.testing.v1 import AppTest
from pathlib import Path

from app.config import PolicyConfig


def test_landing_to_adaptive_feedback_and_next_scenario(tmp_path, monkeypatch):
    import app.config as config

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'ui.db').as_posix()}")
    monkeypatch.setattr(config, "DEFAULT_POLICY", PolicyConfig(pretest_scenario_ids=(), posttest_scenario_ids=()))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app/main.py").run()
    assert not app.exception
    app.button[0].click().run()
    app.text_input[0].set_value("P-UI-1").run()
    app.button[0].click().run()
    assert app.session_state.game.current_scenario_id == "S1A"
    app.checkbox[0].check()
    app.checkbox[1].check()
    app.checkbox[2].check()
    app.multiselect[0].set_value(["falling_objects", "foot_impact", "moving_equipment"])
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state.screen == "feedback"
    assert app.session_state.game.latest_result.safe
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state.screen == "scenario"
    assert app.session_state.game.current_scenario_id == "S2A"


def test_pretest_screen_is_blinded_and_logs_without_feedback(tmp_path, monkeypatch):
    import app.config as config
    from database.log import assessment_logs, create_log_engine
    from sqlalchemy import select

    url = f"sqlite:///{(tmp_path / 'assessment-ui.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(config, "DEFAULT_POLICY", PolicyConfig(pretest_scenario_ids=("PRE01",), posttest_scenario_ids=()))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app/main.py").run()
    app.button[0].click().run()
    app.text_input[0].set_value("P-UI-ASSESS").run()
    app.button[0].click().run()
    assert app.session_state.screen == "assessment"
    assert not app.metric
    assert not app.session_state.game.latest_result
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state.screen == "scenario"
    assert app.session_state.game.latest_result is None
    with create_log_engine(url).connect() as connection:
        row = connection.execute(select(assessment_logs)).mappings().one()
    assert row["phase"] == "PRE"


def test_posttest_screen_is_blinded_and_logs_without_feedback(tmp_path, monkeypatch):
    import app.config as config
    from app.game import GameSession, start_session
    from data.models import Condition
    from database.log import assessment_logs, create_log_engine
    from sqlalchemy import select

    url = f"sqlite:///{(tmp_path / 'post-ui.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(config, "DEFAULT_POLICY", PolicyConfig(
        pretest_scenario_ids=(), posttest_scenario_ids=("POST01",),
    ))
    engine = create_log_engine(url)
    game = GameSession("P-POST-UI", Condition.CONTROL)
    start_session(game, engine)
    game.assessment_phase = "POST"
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app/main.py").run()
    app.session_state.game = game
    app.session_state.screen = "assessment"
    app.run()
    assert not app.exception and not app.metric
    assert app.session_state.game.latest_result is None
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state.screen == "complete"
    with engine.connect() as connection:
        row = connection.execute(select(assessment_logs)).mappings().one()
    assert row["phase"] == "POST"
