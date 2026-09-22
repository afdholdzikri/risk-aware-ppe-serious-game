"""First playable Streamlit interface for the PPE decision study."""

from html import escape
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from app.config import DEFAULT_POLICY
from app.game import (
    GameSession, next_scenario, present_scenario, start_session,
    submit_assessment_decision, submit_decision,
)
from datetime import datetime, timezone
from data.models import Condition
from data.catalog import HAZARD_CATALOG, PPE_CATALOG
from data.scenarios import assessment_by_id, scenario_by_id
from database.log import create_log_engine, default_database_url


st.set_page_config(page_title="Risk-Aware PPE | Decision Lab", page_icon="◈", layout="wide")
css = (Path(__file__).resolve().parents[1] / "assets/css/style.css").read_text(encoding="utf-8")
st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


@st.cache_resource
def _cached_engine(url: str):
    """Reuse a connection pool for a specific configured database URL."""
    return create_log_engine(url)


def log_engine():
    """Resolve configuration before consulting the resource cache."""
    return _cached_engine(default_database_url())


def section(kicker: str, title: str, description: str = "") -> None:
    """Render escaped editorial section text."""
    st.markdown(f'<div class="section-head"><span class="eyebrow">{escape(kicker)}</span>'
                f'<h2>{escape(title)}</h2><p>{escape(description)}</p></div>', unsafe_allow_html=True)


def header() -> None:
    """Render the research dashboard masthead."""
    st.markdown('<div class="masthead"><div class="brand-mark">◈</div><div class="brand-copy">'
                '<strong>RISK-AWARE PPE</strong><span>DECISION LAB / RESEARCH MVP</span></div>'
                '<div class="masthead-tag">INDUSTRIAL SAFETY SIMULATION</div></div>', unsafe_allow_html=True)


def landing() -> None:
    """Introduce the experiment without revealing answers."""
    st.markdown('<div class="hero"><span class="eyebrow">FIELD SIMULATION · VERSION 1.0</span>'
                '<h1>Make the call.<br><em>Before the exposure.</em></h1>'
                '<p>Review workplace situations, identify the hazards, and choose protective equipment. '
                'Your decisions shape the next exposure in the adaptive condition.</p>'
                '<div class="hero-rule"></div><div class="hero-stats"><span><b>06</b> scenario domains</span>'
                '<span><b>12</b> training decisions</span><span><b>01</b> decision at a time</span></div></div>',
                unsafe_allow_html=True)
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown('<div class="mini-title">HOW IT WORKS</div>', unsafe_allow_html=True)
        st.markdown("**01** Read the scenario.\n\n**02** Select PPE and identify hazards.\n\n**03** Review feedback and continue.")
    with right:
        st.markdown('<div class="mini-title">STUDY NOTE</div>', unsafe_allow_html=True)
        st.markdown("This research prototype uses fictional scenarios. Follow your workplace procedures for real safety decisions.")
    if st.button("Begin simulation  →", type="primary", use_container_width=True):
        st.session_state.screen = "participant"
        st.rerun()


def participant() -> None:
    """Collect a pseudonymous code and facilitator-selected condition."""
    section("01 / ACCESS", "Participant setup", "Enter your study code to start a fresh run.")
    with st.form("participant_form"):
        code = st.text_input("Participant code", max_chars=64, placeholder="e.g. P-104",
                             help="Use a study code, not a name or email address.")
        label = st.radio("Experimental condition", ["Adaptive", "Control"], horizontal=True,
                         help="For this MVP, the study facilitator selects the assigned condition.")
        submitted = st.form_submit_button("Start scenarios  →", type="primary", use_container_width=True)
    if submitted:
        if not code.strip():
            st.error("Enter a participant code.")
            return
        game = GameSession(code.strip(), Condition.ADAPTIVE if label == "Adaptive" else Condition.CONTROL)
        try:
            start_session(game, log_engine())
        except ValueError as error:
            st.error(str(error))
            return
        except Exception:
            st.error("The interaction log is unavailable. Ask the facilitator to check the database connection.")
            return
        if DEFAULT_POLICY.pretest_scenario_ids:
            game.assessment_phase = "PRE"
            st.session_state.screen = "assessment"
        else:
            chosen = next_scenario(game, DEFAULT_POLICY)
            if chosen:
                present_scenario(game, chosen, DEFAULT_POLICY)
            st.session_state.screen = "scenario"
        st.session_state.game = game
        st.rerun()


def progress(game: GameSession) -> None:
    """Show current exposure and bounded run progress."""
    total = DEFAULT_POLICY.training_attempts
    current = min(len(game.exposures) + 1, total)
    st.markdown(f'<div class="run-meta"><span>SESSION <b>{escape(game.session_id[:8].upper())}</b></span>'
                f'<span>CONDITION <b>{escape(game.condition.value)}</b></span>'
                f'<span>EXPOSURE <b>{current:02d} / {total:02d}</b></span></div>', unsafe_allow_html=True)
    st.progress(min(len(game.exposures) / total, 1.0))


def scenario_screen(game: GameSession) -> None:
    """Render scenario, PPE cards, and hazard recognition inputs."""
    if game.current_scenario_id is None:
        chosen = next_scenario(game, DEFAULT_POLICY)
        if chosen is None:
            st.session_state.screen = "complete"
            st.rerun()
        present_scenario(game, chosen, DEFAULT_POLICY)
    content = scenario_by_id(game.current_scenario_id)
    progress(game)
    st.markdown(f'<div class="scenario-card"><div class="scenario-top">'
                f'<span class="eyebrow">ACTIVE SCENARIO / {escape(content.scenario.id)}</span>'
                f'<span class="scenario-pill">{escape(content.location)}</span></div>'
                f'<h1>{escape(content.title)}</h1><p class="situation">{escape(content.situation)}</p>'
                f'<div class="task-block"><span>YOUR TASK</span><p>{escape(content.task)}</p></div></div>',
                unsafe_allow_html=True)
    section("02 / EQUIPMENT", "Select protective equipment", "Select every item you would wear before starting.")
    form_key = f"decision-{len(game.exposures)}-{content.scenario.id}"
    with st.form(form_key):
        chosen_ppe: set[str] = set()
        options = [(item_id, PPE_CATALOG[item_id]) for item_id in content.candidate_ppe]
        for start in range(0, len(options), 3):
            cols = st.columns(3, gap="medium")
            for col, (ppe_id, item) in zip(cols, options[start:start + 3]):
                with col:
                    st.markdown(f'<div class="ppe-copy"><span class="ppe-index">{escape(ppe_id.upper().replace("_", " "))}</span>'
                                f'<strong>{escape(item.label)}</strong><small>{escape(item.detail)}</small></div>',
                                unsafe_allow_html=True)
                    if st.checkbox("Select item", key=f"{form_key}-{ppe_id}"):
                        chosen_ppe.add(ppe_id)
        st.markdown('<div class="hazard-heading">HAZARD RECOGNITION</div>', unsafe_allow_html=True)
        hazards = st.multiselect("Which hazards are present?", list(content.candidate_hazards),
                                 format_func=lambda key: HAZARD_CATALOG[key].label,
                                 key=f"{form_key}-hazards", placeholder="Select all hazards you identify")
        submitted = st.form_submit_button("Submit decision  →", type="primary", use_container_width=True)
    if submitted:
        try:
            submit_decision(game, chosen_ppe, set(hazards), log_engine(), DEFAULT_POLICY)
        except Exception:
            st.error("Your decision could not be saved. Please retry; no progress was recorded.")
            return
        st.session_state.screen = "feedback"
        st.rerun()


def feedback_screen(game: GameSession) -> None:
    """Display score, safety result, and adaptive continuation."""
    result = game.latest_result
    if result is None:
        st.session_state.screen = "scenario"
        st.rerun()
    tone = "safe" if result.safe else "unsafe"
    status = f"{result.decision_state} DECISION"
    score_text = f'<h1>{result.pdss:.0f}% <small>PDSS</small></h1>' if game.condition == Condition.ADAPTIVE else ""
    st.markdown(f'<div class="feedback-card {tone}"><span class="eyebrow">03 / DECISION FEEDBACK</span>'
                f'<div class="feedback-status">{status}</div>{score_text}'
                f'<p>{escape(game.latest_feedback or "")}</p></div>', unsafe_allow_html=True)
    if game.condition == Condition.ADAPTIVE:
        a, b, c = st.columns(3, gap="medium")
        a.metric("PPE Requirement Coverage", f"{result.required_ppe_coverage:.0f}%")
        b.metric("Hazard Recognition", f"{result.hra:.0f}%")
        c.metric("Critical PPE", "FAIL" if result.critical_error else "PASS")
        missing = ", ".join(sorted(result.omitted_ppe)) or "None"
        st.markdown(f"**Missing required PPE:** {escape(missing)}")
        hazard = game.exposures[-1].hazard_id
        state = game.competence[hazard]
        focus = game.latest_reinforcement_focus or "None"
        st.markdown(f'<div class="competence-strip"><span>Player Competence <strong>{state.value:.0%}</strong></span>'
                    f'<span>Safe Streak <strong>{state.consecutive_safe}</strong></span>'
                    f'<span>Reinforcement Focus <strong>{escape(focus)}</strong></span></div>', unsafe_allow_html=True)
    chosen = next_scenario(game, DEFAULT_POLICY)
    label = ("Continue to next scenario  →" if chosen else
             "Continue to post-test  →" if DEFAULT_POLICY.posttest_scenario_ids else
             "View session summary  →")
    if st.button(label, type="primary", use_container_width=True):
        if chosen:
            present_scenario(game, chosen, DEFAULT_POLICY)
            st.session_state.screen = "scenario"
        elif DEFAULT_POLICY.posttest_scenario_ids:
            game.assessment_phase = "POST"
            game.assessment_index = 0
            st.session_state.screen = "assessment"
        else:
            st.session_state.screen = "complete"
        st.rerun()


def assessment_screen(game: GameSession) -> None:
    """Collect blinded pre/post responses without displaying decision feedback."""
    phase = game.assessment_phase
    ids = DEFAULT_POLICY.pretest_scenario_ids if phase == "PRE" else DEFAULT_POLICY.posttest_scenario_ids
    if phase not in {"PRE", "POST"} or game.assessment_index >= len(ids):
        st.error("Assessment configuration is incomplete.")
        return
    content = assessment_by_id(ids[game.assessment_index])
    if game.assessment_started_at is None:
        game.assessment_started_at = datetime.now(timezone.utc)
    section(f"{phase}-TEST / ITEM {game.assessment_index + 1}", content.title, content.situation)
    st.markdown(f'<div class="scenario-card"><span class="eyebrow">{escape(content.location)}</span>'
                f'<div class="task-block"><span>YOUR TASK</span><p>{escape(content.task)}</p></div></div>',
                unsafe_allow_html=True)
    with st.form(f"assessment-{phase}-{game.assessment_index}"):
        st.markdown('<div class="hazard-heading">A / HAZARD RECOGNITION</div>', unsafe_allow_html=True)
        hazards = st.multiselect("Select all applicable hazards", list(content.candidate_hazards),
                                 format_func=lambda key: HAZARD_CATALOG[key].label,
                                 key=f"assessment-{phase}-{game.assessment_index}-hazards")
        st.markdown('<div class="hazard-heading">B / PPE SELECTION</div>', unsafe_allow_html=True)
        selected = set()
        for ppe_id in content.candidate_ppe:
            item = PPE_CATALOG[ppe_id]
            if st.checkbox(f"{item.label} — {item.detail}", key=f"assessment-{phase}-{game.assessment_index}-{ppe_id}"):
                selected.add(ppe_id)
        submitted = st.form_submit_button("Save response and continue  →", type="primary", use_container_width=True)
    if submitted:
        last_item = game.assessment_index + 1 == len(ids)
        try:
            submit_assessment_decision(game, content, selected, set(hazards), log_engine(), phase,
                                       game.assessment_started_at,
                                       close_session=(phase == "POST" and last_item),
                                       policy=DEFAULT_POLICY)
        except Exception:
            st.error("Your response could not be saved. Please retry.")
            return
        game.assessment_started_at = None
        game.assessment_index += 1
        if last_item:
            game.assessment_phase = None
            game.assessment_index = 0
            if phase == "PRE":
                chosen = next_scenario(game, DEFAULT_POLICY)
                if chosen:
                    present_scenario(game, chosen, DEFAULT_POLICY)
                st.session_state.screen = "scenario"
            else:
                st.session_state.screen = "complete"
        st.rerun()


def complete_screen(game: GameSession) -> None:
    """Summarize the completed run without exposing answer keys."""
    st.markdown('<div class="complete-card"><span class="eyebrow">SIMULATION COMPLETE</span>'
                '<h1>Session recorded.</h1><p>Your decisions have been saved for research review.</p></div>',
                unsafe_allow_html=True)
    a, b, c = st.columns(3)
    a.metric("Exposures", len(game.exposures))
    b.metric("Safe decisions", sum(item.safe for item in game.exposures))
    c.metric("Condition", game.condition.value)
    st.caption(f"Session reference: {game.session_id}")
    if st.button("Start a new session", use_container_width=True):
        st.session_state.pop("game", None)
        st.session_state.screen = "landing"
        st.rerun()


def main() -> None:
    """Route the browser through the complete playable flow."""
    st.session_state.setdefault("screen", "landing")
    header()
    screen = st.session_state.screen
    game = st.session_state.get("game")
    if screen == "landing":
        landing()
    elif screen == "participant":
        participant()
    elif game is None:
        st.session_state.screen = "landing"
        st.rerun()
    elif screen == "scenario":
        scenario_screen(game)
    elif screen == "feedback":
        feedback_screen(game)
    elif screen == "assessment":
        assessment_screen(game)
    elif screen == "complete":
        complete_screen(game)


if __name__ == "__main__":
    main()
