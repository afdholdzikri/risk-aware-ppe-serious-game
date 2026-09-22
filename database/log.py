"""Portable research schema and transactional write operations.

SQLAlchemy types and foreign keys work with SQLite and PostgreSQL. All records
use pseudonymous participant codes; names and contact details are not collected.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, MetaData,
    String, Table, UniqueConstraint, create_engine, event, insert, inspect, select, text, update,
)
from sqlalchemy.engine import Engine


metadata = MetaData()

participants = Table(
    "participants", metadata,
    Column("participant_id", String(36), primary_key=True),
    Column("participant_code", String(64), unique=True, nullable=False),
    Column("group", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

sessions = Table(
    "sessions", metadata,
    Column("session_id", String(36), primary_key=True),
    Column("participant_id", String(36), ForeignKey("participants.participant_id"), nullable=False),
    Column("group", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
)

assessment_logs = Table(
    "assessment_logs", metadata,
    Column("assessment_id", Integer, primary_key=True, autoincrement=True),
    Column("participant_id", String(36), ForeignKey("participants.participant_id"), nullable=False),
    Column("session_id", String(36), ForeignKey("sessions.session_id"), nullable=False),
    Column("phase", String(32), nullable=False),
    Column("item_id", String(16), nullable=False),
    Column("score", Float),
    Column("details", JSON, nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
)
Index("uq_assessment_session_phase_item", assessment_logs.c.session_id,
      assessment_logs.c.phase, assessment_logs.c.item_id, unique=True)

training_logs = Table(
    "training_logs", metadata,
    Column("training_log_id", Integer, primary_key=True, autoincrement=True),
    Column("participant_id", String(36), ForeignKey("participants.participant_id"), nullable=False),
    Column("session_id", String(36), ForeignKey("sessions.session_id"), nullable=False),
    Column("group", String(16), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("scenario_id", String(64), nullable=False),
    Column("domain_id", String(16)),
    Column("content_status", String(48)),
    Column("scenario_version", String(32), nullable=False),
    Column("policy_version", String(32), nullable=False),
    Column("complexity", Integer, nullable=False),
    Column("selected_ppe", JSON, nullable=False),
    Column("required_ppe", JSON, nullable=False),
    Column("missing_ppe", JSON, nullable=False),
    Column("extra_ppe", JSON, nullable=False),
    Column("selected_hazards", JSON, nullable=False),
    Column("identified_hazards", JSON, nullable=False),
    Column("pdss", Float, nullable=False),
    Column("ppe_accuracy", Float, nullable=False),
    Column("hazard_accuracy", Float, nullable=False),
    Column("hra", Float, nullable=False),
    Column("required_ppe_coverage", Float, nullable=False),
    Column("pda", Integer, nullable=False),
    Column("os", Integer, nullable=False),
    Column("decision_state", String(16), nullable=False),
    Column("critical_error", Boolean, nullable=False),
    Column("decision_time", Float, nullable=False),
    Column("competence_before", Float, nullable=False),
    Column("competence_after", Float, nullable=False),
    Column("safe_streak", Integer, nullable=False),
    Column("remedial_flag", Boolean, nullable=False),
    Column("target_error", String(128)),
    Column("reinforcement_focus", String(128)),
    Column("risk_priorities", JSON, nullable=False),
    Column("risk_priority_source", String(32), nullable=False),
    Column("expert_validation_status", String(16)),
    Column("primary_expert_panel_n", Integer),
    Column("followup_expert_panel_n", Integer),
    Column("hazard_source", String(48)),
    Column("next_scenario", String(64)),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    UniqueConstraint("session_id", "attempt", name="uq_training_session_attempt"),
)


def default_database_url() -> str:
    """Resolve credentials from environment, then Streamlit secrets, then SQLite.

    `DATABASE_URL` takes precedence so deployments can inject a PostgreSQL URL.
    A missing local secrets file is normal outside a deployed Streamlit app.
    """
    configured = os.environ.get("DATABASE_URL")
    if configured:
        return configured
    try:
        import streamlit as st
        configured = st.secrets.get("DATABASE_URL")
    except FileNotFoundError:
        configured = None
    if configured:
        return str(configured)
    path = Path(__file__).resolve().parent / "ppe_game.db"
    return f"sqlite:///{path.as_posix()}"


def create_log_engine(database_url: str | None = None) -> Engine:
    """Connect to SQLite or PostgreSQL and create missing research tables."""
    url = database_url or default_database_url()
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    metadata.create_all(engine)
    _add_training_columns_to_legacy_table(engine)
    _add_assessment_item_to_legacy_table(engine)
    return engine


def _add_training_columns_to_legacy_table(engine: Engine) -> None:
    """Add audit variables to a previous MVP table without deleting its rows.

    Legacy rows remain nullable for fields not collected at the time. New rows
    always populate the complete set. This is an additive compatibility step,
    not a replacement for managed schema migrations in a deployed study.
    """
    existing = {column["name"] for column in inspect(engine).get_columns("training_logs")}
    additions = {
        "extra_ppe": "JSON",
        "selected_hazards": "JSON",
        "hra": "FLOAT",
        "required_ppe_coverage": "FLOAT",
        "pda": "INTEGER",
        "os": "INTEGER",
        "safe_streak": "INTEGER",
        "reinforcement_focus": "VARCHAR(128)",
        "risk_priorities": "JSON",
        "risk_priority_source": "VARCHAR(32)",
        "domain_id": "VARCHAR(16)",
        "content_status": "VARCHAR(48)",
        "expert_validation_status": "VARCHAR(16)",
        "primary_expert_panel_n": "INTEGER",
        "followup_expert_panel_n": "INTEGER",
        "hazard_source": "VARCHAR(48)",
    }
    with engine.begin() as connection:
        for name, data_type in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE training_logs ADD COLUMN {name} {data_type}"))


def _add_assessment_item_to_legacy_table(engine: Engine) -> None:
    """Add a stable item key and unique index to earlier assessment tables."""
    existing = {column["name"] for column in inspect(engine).get_columns("assessment_logs")}
    with engine.begin() as connection:
        if "item_id" not in existing:
            connection.execute(text("ALTER TABLE assessment_logs ADD COLUMN item_id VARCHAR(16)"))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_assessment_session_phase_item "
            "ON assessment_logs (session_id, phase, item_id)"
        ))


def register_session(engine: Engine, participant_code: str, group: str, session_id: str) -> str:
    """Create a session and reuse a participant ID for a repeated study code.

    Existing codes keep their originally assigned condition to avoid accidental
    crossover within the same research dataset.
    """
    code = participant_code.strip()
    if not code or len(code) > 64:
        raise ValueError("participant code must contain 1–64 characters")
    if group not in {"CONTROL", "ADAPTIVE"}:
        raise ValueError("invalid experimental group")
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        row = connection.execute(select(participants).where(participants.c.participant_code == code)).mappings().first()
        if row:
            if row["group"] != group:
                raise ValueError("participant code is already assigned to another group")
            participant_id = row["participant_id"]
        else:
            participant_id = str(uuid4())
            connection.execute(insert(participants).values(
                participant_id=participant_id, participant_code=code,
                group=group, created_at=now,
            ))
        connection.execute(insert(sessions).values(
            session_id=session_id, participant_id=participant_id, group=group,
            status="ACTIVE", started_at=now,
        ))
    return participant_id


def append_training_decision(engine: Engine, values: dict[str, Any], close_session: bool = True) -> None:
    """Commit a training row once and complete the session when appropriate.

    A rerun with the same session/attempt/response is idempotent. Conflicting
    responses for an already recorded attempt raise instead of overwriting it.
    """
    with engine.begin() as connection:
        existing = connection.execute(select(training_logs).where(
            training_logs.c.session_id == values["session_id"],
            training_logs.c.attempt == values["attempt"],
        )).mappings().first()
        if existing:
            comparable = ("scenario_id", "selected_ppe", "selected_hazards", "decision_state")
            if any(existing[key] != values[key] for key in comparable):
                raise ValueError("attempt already recorded with a different response")
            return
        connection.execute(insert(training_logs).values(**values))
        if close_session and values["next_scenario"] is None:
            connection.execute(update(sessions).where(sessions.c.session_id == values["session_id"]).values(
                status="COMPLETED", completed_at=values["timestamp"],
            ))


def append_assessment(
    engine: Engine, participant_id: str, session_id: str, phase: str,
    score: float | None, details: dict[str, Any], close_session: bool = False,
) -> None:
    """Persist one blinded item, idempotently across Streamlit reruns."""
    item_id = details.get("scenario_id")
    if not item_id or phase not in {"PRE", "POST"}:
        raise ValueError("assessment phase and item ID are required")
    with engine.begin() as connection:
        existing = connection.execute(select(assessment_logs).where(
            assessment_logs.c.session_id == session_id,
            assessment_logs.c.phase == phase,
            assessment_logs.c.item_id == item_id,
        )).mappings().first()
        if existing:
            if existing["details"].get("selected_ppe") != details.get("selected_ppe") or \
               existing["details"].get("selected_hazards") != details.get("selected_hazards"):
                raise ValueError("assessment item already recorded with a different response")
            return
        connection.execute(insert(assessment_logs).values(
            participant_id=participant_id, session_id=session_id, phase=phase, item_id=item_id,
            score=score, details=details, timestamp=datetime.now(timezone.utc),
        ))
        if close_session:
            connection.execute(update(sessions).where(sessions.c.session_id == session_id).values(
                status="COMPLETED", completed_at=datetime.now(timezone.utc),
            ))
